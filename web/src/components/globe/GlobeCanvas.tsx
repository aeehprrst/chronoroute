/**
 * The 3D view (three.js through React Three Fiber). Loaded lazily by GlobeIsland so that
 * pages stay light until the globe is on screen.
 *
 * World frame = Earth-centred inertial (TEME). The Earth and the reference cities sit in a
 * group rotated by GMST; satellites are drawn in the inertial frame directly.
 */
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  LineBasicMaterial,
  LineLoop,
  LinearMipmapLinearFilter,
  Points,
  SRGBColorSpace,
  ShaderMaterial,
  TextureLoader,
  Vector3,
  type Group,
  type PerspectiveCamera,
  type Texture,
} from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { assetHref } from '../../lib/paths';
import { gmstRad, kmToScene, rotateSceneY } from '../../lib/orbit/frames';
import { sunPosition } from '../../lib/orbit/sun';
import { createEarthGeometry, geodeticToScene, REFERENCE_CITIES } from '../../lib/orbit/earth-geometry';
import { interpolateRow } from '../../lib/orbit/interp';
import { SHELLS } from '../../lib/orbit/shells';
import {
  EARTH_FRAGMENT,
  EARTH_VERTEX,
  MARKER_FRAGMENT,
  MARKER_VERTEX,
  SAT_FRAGMENT,
  SAT_VERTEX,
} from './shaders';
import type { EngineFrame, GlobeEngine } from './engine';
import { pickSatellite } from './pick';

export interface GlobeCanvasProps {
  engine: GlobeEngine;
  variant: 'live' | 'mini';
  /** True on narrow or touch screens: smaller textures, lower pixel ratio. */
  compact: boolean;
  reducedMotion: boolean;
  /** Pause rendering (e.g. when the globe is scrolled off screen). */
  active: boolean;
  /**
   * Touch screens (live globe): while true, the orbit controls are off and a swipe over the
   * globe scrolls the page; taps still pick satellites. The reader turns it off with "Move globe".
   */
  touchLocked?: boolean;
  onPick: (index: number) => void;
  onContextLost: () => void;
}

/** Camera distance limits (scene units from the Earth's centre). */
const MIN_DISTANCE = 1.25;
const MAX_DISTANCE = 12;

/** Initial camera direction: looking at the sunlit side, with the terminator in view. */
function initialCameraDirection(simMs: number): Vector3 {
  const sun = kmToScene(sunPosition(simMs).eci);
  const dir = new Vector3(sun.x, sun.y, sun.z).normalize();
  // Turn 50 degrees away from the Sun about the north axis and tilt 20 degrees north.
  const turned = rotateSceneY(dir, (50 * Math.PI) / 180);
  const v = new Vector3(turned.x, 0, turned.z).normalize();
  const tilt = (20 * Math.PI) / 180;
  return new Vector3(v.x * Math.cos(tilt), Math.sin(tilt), v.z * Math.cos(tilt)).normalize();
}

/** Camera distance at which a sphere of radius `r` fits the view with a margin. */
function fitDistance(camera: PerspectiveCamera, r: number): number {
  const vfov = (camera.fov * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
  const half = Math.min(vfov, hfov) / 2;
  return r / Math.sin(half * 0.9);
}

function Earth({ engine, compact, earthGroup }: { engine: GlobeEngine; compact: boolean; earthGroup: React.RefObject<Group | null> }) {
  const gl = useThree((s) => s.gl);
  const geometry = useMemo(() => createEarthGeometry(compact ? 128 : 192, compact ? 64 : 96), [compact]);
  const material = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: EARTH_VERTEX,
        fragmentShader: EARTH_FRAGMENT,
        uniforms: {
          dayMap: { value: null },
          nightMap: { value: null },
          texturesReady: { value: 0 },
          sunDir: { value: new Vector3(1, 0, 0) },
        },
      }),
    [],
  );

  useEffect(() => {
    let cancelled = false;
    const size = compact || gl.capabilities.maxTextureSize < 4096 ? 2048 : 4096;
    const loader = new TextureLoader();
    const load = (name: string) =>
      new Promise<Texture>((resolve, reject) => {
        loader.load(assetHref(`textures/${name}-${size}.jpg`), resolve, undefined, reject);
      });
    Promise.all([load('earth-day'), load('earth-night')])
      .then(([day, night]) => {
        if (cancelled) {
          day.dispose();
          night.dispose();
          return;
        }
        for (const t of [day, night]) {
          t.colorSpace = SRGBColorSpace;
          t.anisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy());
          t.minFilter = LinearMipmapLinearFilter;
          t.needsUpdate = true;
        }
        material.uniforms['dayMap']!.value = day;
        material.uniforms['nightMap']!.value = night;
        material.uniforms['texturesReady']!.value = 1;
      })
      .catch((error: unknown) => {
        // Without textures the Earth stays a plain dark sphere; satellites are unaffected.
        console.warn('Earth textures could not be loaded:', error);
      });
    return () => {
      cancelled = true;
      (material.uniforms['dayMap']!.value as Texture | null)?.dispose();
      (material.uniforms['nightMap']!.value as Texture | null)?.dispose();
    };
  }, [compact, gl, material]);

  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => material.dispose(), [material]);

  useFrame(() => {
    const sun = kmToScene(sunPosition(engine.simMs).eci);
    (material.uniforms['sunDir']!.value as Vector3).set(sun.x, sun.y, sun.z).normalize();
    if (earthGroup.current) earthGroup.current.rotation.y = gmstRad(engine.simMs);
  });

  return <mesh geometry={geometry} material={material} renderOrder={0} />;
}

function Satellites({ engine, compact }: { engine: GlobeEngine; compact: boolean }) {
  const camera = useThree((s) => s.camera);
  const dpr = useThree((s) => s.viewport.dpr);
  const n = engine.meta.count;
  const { geometry, posA, posB } = useMemo(() => {
    const g = new BufferGeometry();
    const a = new BufferAttribute(new Float32Array(n * 3), 3);
    const b = new BufferAttribute(new Float32Array(n * 3), 3);
    const shell = new BufferAttribute(new Float32Array(engine.meta.shell), 1);
    g.setAttribute('position', a);
    g.setAttribute('posB', b);
    g.setAttribute('shell', shell);
    return { geometry: g, posA: a, posB: b };
  }, [engine, n]);
  const material = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: SAT_VERTEX,
        fragmentShader: SAT_FRAGMENT,
        transparent: true,
        depthWrite: false,
        uniforms: {
          uAlpha: { value: 0 },
          uSize: { value: 2 },
          uVisible: { value: SHELLS.map(() => 1) },
          uColors: { value: SHELLS.map((s) => new Color(s.color)) },
        },
      }),
    [],
  );
  const shown = useRef<{ a: EngineFrame | null; b: EngineFrame | null; vis: number }>({ a: null, b: null, vis: -1 });

  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => material.dispose(), [material]);

  useFrame(() => {
    const pair = engine.pair;
    const s = shown.current;
    if (pair) {
      if (pair.a !== s.a) {
        (posA.array as Float32Array).set(pair.a.positions);
        posA.needsUpdate = true;
        s.a = pair.a;
      }
      if (pair.b !== s.b) {
        (posB.array as Float32Array).set(pair.b.positions);
        posB.needsUpdate = true;
        s.b = pair.b;
      }
      material.uniforms['uAlpha']!.value = pair.alpha;
    }
    if (engine.visibilityVersion !== s.vis) {
      material.uniforms['uVisible']!.value = engine.visible.map((v) => (v ? 1 : 0));
      s.vis = engine.visibilityVersion;
    }
    // Point size in device pixels: about 2 CSS px from afar, growing a little when zoomed in.
    const dist = camera.position.length();
    const cssPx = Math.min(4, Math.max(compact ? 2 : 1.6, 6.4 / dist));
    material.uniforms['uSize']!.value = cssPx * dpr;
  });

  return <points geometry={geometry} material={material} frustumCulled={false} renderOrder={2} />;
}

function Selection({ engine }: { engine: GlobeEngine }) {
  const dpr = useThree((s) => s.viewport.dpr);
  const markerGeometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(new Float32Array(3), 3));
    return g;
  }, []);
  const markerMaterial = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: MARKER_VERTEX,
        fragmentShader: MARKER_FRAGMENT,
        transparent: true,
        depthWrite: false,
        uniforms: { uSize: { value: 18 }, uColor: { value: new Color('#ffffff') } },
      }),
    [],
  );
  const trackMaterial = useMemo(
    () => new LineBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.55, depthWrite: false }),
    [],
  );
  const marker = useMemo(() => {
    const m = new Points(markerGeometry, markerMaterial);
    m.frustumCulled = false;
    m.renderOrder = 3;
    m.visible = false;
    return m;
  }, [markerGeometry, markerMaterial]);
  const trackLine = useMemo(() => {
    const l = new LineLoop(new BufferGeometry(), trackMaterial);
    l.frustumCulled = false;
    l.renderOrder = 1;
    l.visible = false;
    return l;
  }, [trackMaterial]);
  const shownTrack = useRef<Float32Array | null>(null);
  const tmp = useMemo(() => new Float32Array(3), []);

  useEffect(
    () => () => {
      markerGeometry.dispose();
      markerMaterial.dispose();
      trackLine.geometry.dispose();
      trackMaterial.dispose();
    },
    [markerGeometry, markerMaterial, trackLine, trackMaterial],
  );

  useFrame(() => {
    const i = engine.selected;
    const pair = engine.pair;
    let ok = false;
    if (i >= 0 && pair) {
      ok = interpolateRow(pair.a.positions, pair.b.positions, i, pair.alpha, tmp);
      if (ok) {
        const attr = markerGeometry.getAttribute('position') as BufferAttribute;
        (attr.array as Float32Array).set(tmp);
        attr.needsUpdate = true;
      }
    }
    marker.visible = ok;
    markerMaterial.uniforms['uSize']!.value = 18 * dpr;

    const track = engine.track && engine.track.index === i ? engine.track.points : null;
    if (track !== shownTrack.current) {
      shownTrack.current = track;
      if (track && track.length >= 6) {
        const old = trackLine.geometry;
        const g = new BufferGeometry();
        g.setAttribute('position', new BufferAttribute(track, 3));
        trackLine.geometry = g;
        old.dispose();
        const shell = SHELLS[engine.meta.shell[i] ?? 4];
        trackMaterial.color.set(shell ? shell.color : '#ffffff');
      }
    }
    trackLine.visible = !!track && track.length >= 6;
  });

  return (
    <>
      <primitive object={trackLine} />
      <primitive object={marker} />
    </>
  );
}

function Cities({ labelLayer }: { labelLayer: React.RefObject<HTMLDivElement | null> }) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const positions = useMemo(
    () => REFERENCE_CITIES.map((c) => geodeticToScene(c.latDeg, c.lonDeg, 0)),
    [],
  );
  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    const arr = new Float32Array(positions.length * 3);
    positions.forEach((p, k) => {
      // 3 km above the surface so the dot is never hidden inside the Earth mesh.
      const s = 1 + 3 / 6378.137;
      arr[k * 3] = p.x * s;
      arr[k * 3 + 1] = p.y * s;
      arr[k * 3 + 2] = p.z * s;
    });
    g.setAttribute('position', new BufferAttribute(arr, 3));
    return g;
  }, [positions]);
  const groupRef = useRef<Group | null>(null);
  const v = useMemo(() => new Vector3(), []);
  const normal = useMemo(() => new Vector3(), []);
  const toCam = useMemo(() => new Vector3(), []);

  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame(() => {
    const layer = labelLayer.current;
    // The group sits inside the Earth group (rotated by GMST); its world matrix is the Earth's.
    const group = groupRef.current;
    if (!layer || !group) return;
    const labels = layer.children;
    positions.forEach((p, k) => {
      const el = labels[k] as HTMLElement | undefined;
      if (!el) return;
      v.set(p.x, p.y, p.z).applyMatrix4(group.matrixWorld);
      normal.copy(v).normalize();
      toCam.copy(camera.position).sub(v).normalize();
      const facing = normal.dot(toCam) > 0.08;
      v.project(camera);
      const onScreen = v.z < 1 && Math.abs(v.x) < 1 && Math.abs(v.y) < 1;
      if (facing && onScreen) {
        const x = ((v.x + 1) / 2) * size.width;
        const y = ((1 - v.y) / 2) * size.height;
        el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
        el.hidden = false;
      } else {
        el.hidden = true;
      }
    });
  });

  return (
    <group ref={groupRef}>
      <points geometry={geometry} renderOrder={1}>
        <pointsMaterial color="#e6edf7" size={5} sizeAttenuation={false} />
      </points>
    </group>
  );
}

function CameraRig({ engine, variant, reducedMotion }: { engine: GlobeEngine; variant: 'live' | 'mini'; reducedMotion: boolean }) {
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null;
  const placed = useRef(false);
  const lastFly = useRef(0);
  const lastCommand = useRef(0);
  const anim = useRef<{ from: Vector3; to: Vector3; start: number; dist: number } | null>(null);
  const tmp = useMemo(() => new Float32Array(3), []);

  // Place the camera once, at a distance that fits the globe and the satellites.
  useEffect(() => {
    if (placed.current || size.width === 0) return;
    const dist = fitDistance(camera, variant === 'mini' ? 1.12 : 1.2);
    camera.position.copy(initialCameraDirection(engine.simMs).multiplyScalar(dist));
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    controls?.update();
    placed.current = true;
  }, [camera, controls, engine, size, variant]);

  useFrame((state) => {
    const command = engine.cameraCommand;
    if (command && command.serial !== lastCommand.current) {
      lastCommand.current = command.serial;
      anim.current = null;
      if (command.kind === 'reset') {
        const dist = fitDistance(camera, variant === 'mini' ? 1.12 : 1.2);
        camera.position.copy(initialCameraDirection(engine.simMs).multiplyScalar(dist));
      } else {
        const factor = command.kind === 'zoom-in' ? 0.8 : 1.25;
        camera.position.setLength(Math.min(MAX_DISTANCE, Math.max(MIN_DISTANCE, camera.position.length() * factor)));
      }
      camera.lookAt(0, 0, 0);
      controls?.update();
    }
    const fly = engine.fly;
    const pair = engine.pair;
    if (fly && fly.serial !== lastFly.current && pair) {
      lastFly.current = fly.serial;
      if (interpolateRow(pair.a.positions, pair.b.positions, fly.index, pair.alpha, tmp)) {
        const to = new Vector3(tmp[0], tmp[1], tmp[2]).normalize();
        const dist = camera.position.length();
        if (reducedMotion) {
          camera.position.copy(to.multiplyScalar(dist));
          camera.lookAt(0, 0, 0);
          controls?.update();
        } else {
          anim.current = { from: camera.position.clone().normalize(), to, start: state.clock.elapsedTime, dist };
        }
      }
    }
    const a = anim.current;
    if (a) {
      const t = Math.min(1, (state.clock.elapsedTime - a.start) / 0.9);
      const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const angle = a.from.angleTo(a.to);
      let dir: Vector3;
      if (angle < 1e-6) dir = a.to.clone();
      else {
        const s = Math.sin(angle);
        dir = a.from
          .clone()
          .multiplyScalar(Math.sin((1 - e) * angle) / s)
          .add(a.to.clone().multiplyScalar(Math.sin(e * angle) / s));
      }
      camera.position.copy(dir.normalize().multiplyScalar(a.dist));
      camera.lookAt(0, 0, 0);
      controls?.update();
      if (t >= 1) anim.current = null;
    }
  });
  return null;
}

/** Pump the engine once per rendered frame, before the scene components read it. */
function EnginePump({ engine }: { engine: GlobeEngine }) {
  useFrame(() => {
    engine.pump();
  }, -1);
  return null;
}

/**
 * OrbitControls sets `touch-action: none` on the element it listens on (React Three Fiber's
 * event-source div) when it connects. While touch rotation is locked, hand panning and
 * pinch-zoom back to the browser so a swipe scrolls the page; restore `none` when unlocked.
 * Runs after OrbitControls' own effect (later sibling) and again when the default controls change.
 */
function TouchActionSync({ locked }: { locked: boolean }) {
  const gl = useThree((s) => s.gl);
  const connected = useThree((s) => s.events.connected) as HTMLElement | null | undefined;
  const controls = useThree((s) => s.controls);
  useEffect(() => {
    const target = connected ?? gl.domElement;
    target.style.touchAction = locked ? 'manipulation' : 'none';
  }, [gl, connected, controls, locked]);
  return null;
}

function Scene(props: GlobeCanvasProps & { labelLayer: React.RefObject<HTMLDivElement | null>; wheelZoom: boolean }) {
  const { engine, variant, compact, reducedMotion, labelLayer, wheelZoom } = props;
  const touchLocked = props.touchLocked ?? false;
  const earthGroup = useRef<Group | null>(null);
  return (
    <>
      <EnginePump engine={engine} />
      <group ref={earthGroup}>
        <Earth engine={engine} compact={compact} earthGroup={earthGroup} />
        {variant === 'live' && <Cities labelLayer={labelLayer} />}
      </group>
      <Satellites engine={engine} compact={compact} />
      {variant === 'live' && <Selection engine={engine} />}
      {variant === 'live' && (
        <OrbitControls
          makeDefault
          enabled={!touchLocked}
          enablePan={false}
          enableZoom={wheelZoom}
          enableDamping={!reducedMotion}
          dampingFactor={0.08}
          rotateSpeed={0.5}
          zoomSpeed={0.6}
          minDistance={MIN_DISTANCE}
          maxDistance={MAX_DISTANCE}
        />
      )}
      {variant === 'live' && <TouchActionSync locked={touchLocked} />}
      <CameraRig engine={engine} variant={variant} reducedMotion={reducedMotion} />
    </>
  );
}

function GlobeCanvasInner(props: GlobeCanvasProps) {
  const { engine, variant, compact, active, onPick, onContextLost } = props;
  const labelLayer = useRef<HTMLDivElement | null>(null);
  const cameraRef = useRef<PerspectiveCamera | null>(null);
  const down = useRef<{ x: number; y: number; t: number; id: number } | null>(null);
  // Wheel zoom only after the globe has been clicked, so scrolling the page past it never
  // zooms by accident; it is disarmed when the pointer leaves. Pinch zoom (touch) always works.
  const [wheelArmed, setWheelArmed] = useState(false);
  const coarse = useMemo(() => window.matchMedia('(pointer: coarse)').matches, []);

  const canvasEl = useRef<HTMLCanvasElement | null>(null);

  // Listen on the canvas element itself, so a context loss is reported even if it happens
  // before React Three Fiber has finished setting up.
  useEffect(() => {
    const el = canvasEl.current;
    if (!el) return;
    const onLost = (event: Event) => {
      event.preventDefault();
      onContextLost();
    };
    el.addEventListener('webglcontextlost', onLost);
    return () => el.removeEventListener('webglcontextlost', onLost);
  }, [onContextLost]);

  return (
    <div className="globe-canvas">
      <Canvas
        flat
        dpr={[1, compact ? 1.5 : 2]}
        frameloop={active ? 'always' : 'never'}
        camera={{ fov: 35, near: 0.01, far: 100, position: [0, 0, 4] }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        ref={canvasEl}
        onCreated={(state) => {
          cameraRef.current = state.camera as PerspectiveCamera;
        }}
        onPointerDown={(e) => {
          down.current = { x: e.clientX, y: e.clientY, t: performance.now(), id: e.pointerId };
          if (!wheelArmed) setWheelArmed(true);
        }}
        onPointerLeave={() => {
          if (wheelArmed) setWheelArmed(false);
        }}
        onPointerUp={(e) => {
          const d = down.current;
          down.current = null;
          if (variant !== 'live' || !d || d.id !== e.pointerId) return;
          if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6 || performance.now() - d.t > 700) return;
          const camera = cameraRef.current;
          const pair = engine.pair;
          if (!camera || !pair) return;
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          const index = pickSatellite({
            camera,
            pair,
            visible: engine.visible,
            shells: engine.meta.shell,
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
            width: rect.width,
            height: rect.height,
            radiusPx: e.pointerType === 'touch' ? 28 : 16,
          });
          onPick(index);
        }}
        aria-hidden="true"
      >
        <Scene {...props} labelLayer={labelLayer} wheelZoom={coarse || wheelArmed} />
      </Canvas>
      {variant === 'live' && (
        <div className="globe-labels" ref={labelLayer} aria-hidden="true">
          {REFERENCE_CITIES.map((c) => (
            <span key={c.name} className="globe-label" hidden>
              {c.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const GlobeCanvas = memo(GlobeCanvasInner);
export default GlobeCanvas;
