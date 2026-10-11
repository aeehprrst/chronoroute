/**
 * GLSL for the globe. three.js ShaderMaterial adds the standard uniforms (modelMatrix,
 * viewMatrix, projectionMatrix, cameraPosition) and attributes (position, normal, uv).
 * Colours are handled in linear space and converted with <colorspace_fragment>.
 */
import { GLSL_ORBIT_INTERP } from '../../lib/orbit/interp';

/** Earth: day map lit by the real Sun direction, night lights on the dark side. */
export const EARTH_VERTEX = /* glsl */ `
varying vec2 vUv;
varying vec3 vNormalW;
varying vec3 vViewW;

void main() {
  vUv = uv;
  vec4 worldPos = modelMatrix * vec4(position, 1.0);
  // The Earth group is only rotated (no scaling), so mat3(modelMatrix) maps normals correctly.
  vNormalW = normalize(mat3(modelMatrix) * normal);
  vViewW = normalize(cameraPosition - worldPos.xyz);
  gl_Position = projectionMatrix * viewMatrix * worldPos;
}
`;

export const EARTH_FRAGMENT = /* glsl */ `
uniform sampler2D dayMap;
uniform sampler2D nightMap;
uniform float texturesReady;
uniform vec3 sunDir;

varying vec2 vUv;
varying vec3 vNormalW;
varying vec3 vViewW;

void main() {
  vec3 n = normalize(vNormalW);
  float cosSun = dot(n, sunDir);
  // Soft terminator: the transition spans about +-6 degrees of solar elevation (civil twilight).
  float dayWeight = smoothstep(-0.105, 0.105, cosSun);

  vec3 dayTex = texturesReady > 0.5 ? texture2D(dayMap, vUv).rgb : vec3(0.02, 0.05, 0.11);
  vec3 nightTex = texturesReady > 0.5 ? texture2D(nightMap, vUv).rgb : vec3(0.0);

  vec3 dayLit = dayTex * (0.06 + 0.94 * clamp(cosSun * 1.25 + 0.08, 0.0, 1.0));
  vec3 night = nightTex * 1.1 + dayTex * 0.025;
  vec3 color = mix(night, dayLit, dayWeight);

  // Thin limb brightening on the sunlit side, a cue for the atmosphere (not a measured quantity).
  float rim = pow(1.0 - max(dot(n, normalize(vViewW)), 0.0), 4.0);
  color += vec3(0.18, 0.36, 0.75) * rim * 0.45 * smoothstep(-0.15, 0.35, cosSun);

  gl_FragColor = vec4(color, 1.0);
  #include <colorspace_fragment>
}
`;

/**
 * Satellites: one draw call. Attribute position = frame A, posB = frame B; the vertex shader
 * interpolates along the orbit arc (see src/lib/orbit/interp.ts). Rows without a position, and
 * hidden shells, are moved outside the clip volume.
 */
export const SAT_VERTEX = /* glsl */ `
attribute vec3 posB;
attribute float shell;

uniform float uAlpha;
uniform float uSize;
uniform float uVisible[6];
uniform vec3 uColors[6];

varying vec3 vColor;

${GLSL_ORBIT_INTERP}

void main() {
  int s = int(shell + 0.5);
  if (uVisible[s] < 0.5 || length(position) < 0.5 || length(posB) < 0.5) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 0.0;
    vColor = vec3(0.0);
    return;
  }
  vec3 p = orbitInterp(position, posB, uAlpha);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = uSize;
  vColor = uColors[s];
}
`;

export const SAT_FRAGMENT = /* glsl */ `
varying vec3 vColor;

void main() {
  vec2 c = gl_PointCoord * 2.0 - 1.0;
  float d = dot(c, c);
  if (d > 1.0) discard;
  float a = 1.0 - smoothstep(0.45, 1.0, d);
  gl_FragColor = vec4(vColor, a);
  #include <colorspace_fragment>
}
`;

/** Selection marker: a ring around the selected satellite. */
export const MARKER_VERTEX = /* glsl */ `
uniform float uSize;
void main() {
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = uSize;
}
`;

export const MARKER_FRAGMENT = /* glsl */ `
uniform vec3 uColor;
void main() {
  vec2 c = gl_PointCoord * 2.0 - 1.0;
  float r = length(c);
  float ring = smoothstep(0.62, 0.72, r) * (1.0 - smoothstep(0.86, 0.98, r));
  float dot_ = 1.0 - smoothstep(0.18, 0.3, r);
  float a = max(ring, dot_);
  if (a < 0.01) discard;
  gl_FragColor = vec4(uColor, a);
  #include <colorspace_fragment>
}
`;
