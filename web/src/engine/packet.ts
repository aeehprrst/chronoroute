/**
 * A whole IPv6 packet carrying a T-CRH, and a one-file pcap of it. Port of the parts of
 * sim/chronoroute/trace/pcap.py that the route planner needs, so the bytes the site offers
 * for download are the bytes Python writes (the parity test compares them byte for byte).
 *
 * Packet: IPv6 header (Next Header 43 = Routing) + the T-CRH bytes unchanged + a UDP datagram
 * (the T-CRH's own Next Header byte says 17). The UDP checksum uses the IPv6 pseudo-header of
 * RFC 8200 section 8.1 with the FINAL destination: for a T-CRH that is the address of SID[0],
 * the last segment endpoint, not the address currently in the Destination field. Only the
 * routing header's mutable fields and the Destination Address change in flight, so the one
 * checksum stays right at every hop.
 *
 * Addresses (MODELLED, the project's address plan, same as the ns-3 module): SID s -> fd00::s.
 * The sending host is fd00:0:0:ffff::1, outside the SID space fd00::/96.
 *
 * pcap: classic format 2.4, little-endian, nanosecond time stamps (magic 0xA1B23C4D),
 * LINKTYPE_RAW (101): each frame is a bare IPv6 packet. Wireshark opens it directly, and
 * tools/wireshark/tcrh.lua decodes the T-CRH. Time stamps: ChronoRoute times are GPS ns
 * (spec section 4); pcap counts from the Unix epoch, so t_pcap = t_gps + (315964800 - 18) s,
 * which is real UTC for instants after 2017.
 */
import { checkRange } from './timebase';

export const IPPROTO_UDP = 17;
export const IPPROTO_ROUTING = 43;
export const DEFAULT_HOP_LIMIT = 64;
/** UDP port on both ends: unassigned, so Wireshark shows the payload as plain data. */
export const DEFAULT_PORT = 50253;
export const LINKTYPE_RAW = 101;
export const PCAP_MAGIC_NS = 0xa1b23c4d;
export const DEFAULT_SNAPLEN = 262144;
/** Payload "CRT1" + packet id (u32) + send time GPS ns (u64): 16 bytes. */
export const PAYLOAD_MAGIC = [0x43, 0x52, 0x54, 0x31] as const;
const GPS_EPOCH_UNIX_S = 315964800n;
const GPS_UTC_OFFSET_S = 18n;
const NS_PER_S = 1_000_000_000n;
export const GPS_TO_PCAP_NS = (GPS_EPOCH_UNIX_S - GPS_UTC_OFFSET_S) * NS_PER_S;

/** fd00:0:0:ffff::1, the sending host / user terminal. */
export const HOST_SRC: Uint8Array = Uint8Array.from([0xfd, 0, 0, 0, 0, 0, 0xff, 0xff, 0, 0, 0, 0, 0, 0, 0, 1]);

/** fd00::<sid>: the low 32 bits carry the SID (16-bit T-CRH SIDs use the low 16). */
export function sidAddress(sid: number): Uint8Array {
  checkRange('SID', sid, 0, 0xffffffff);
  const out = new Uint8Array(16);
  out[0] = 0xfd;
  new DataView(out.buffer).setUint32(12, sid, false);
  return out;
}

/** "CRT1" + pid (u32) + send time in GPS ns (u64), big-endian. */
export function payloadBytes(pid: number, tSendGpsNs: bigint): Uint8Array {
  checkRange('pid', pid, 0, 0xffffffff);
  if (tSendGpsNs < 0n || tSendGpsNs >= 1n << 64n) throw new RangeError('t_send_gps_ns must fit in 64 bits');
  const out = new Uint8Array(16);
  out.set(PAYLOAD_MAGIC, 0);
  const view = new DataView(out.buffer);
  view.setUint32(4, pid, false);
  view.setBigUint64(8, tSendGpsNs, false);
  return out;
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

/** RFC 1071 Internet checksum (one's complement sum of 16-bit big-endian words). */
export function internetChecksum(data: Uint8Array): number {
  let total = 0;
  for (let i = 0; i < data.length; i += 2) {
    total += (data[i]! << 8) | (i + 1 < data.length ? data[i + 1]! : 0);
  }
  while (total > 0xffff) total = (total & 0xffff) + Math.floor(total / 0x10000);
  return ~total & 0xffff;
}

/** RFC 8200 8.1 pseudo-header: source, FINAL destination, 32-bit length, 3 zero bytes, Next Header. */
export function pseudoHeader(src: Uint8Array, finalDst: Uint8Array, upperLength: number, nextHeader: number): Uint8Array {
  const tail = new Uint8Array(8);
  new DataView(tail.buffer).setUint32(0, upperLength, false);
  tail[7] = nextHeader;
  return concat(src, finalDst, tail);
}

/** UDP header + payload; checksum over the pseudo-header naming the final destination (0 sent as 0xFFFF). */
export function udpDatagram(src: Uint8Array, finalDst: Uint8Array, payload: Uint8Array, sport = DEFAULT_PORT, dport = DEFAULT_PORT): Uint8Array {
  const length = 8 + payload.length;
  if (length > 0xffff) throw new RangeError(`UDP datagram of ${length} bytes is too long`);
  const header = new Uint8Array(8);
  const view = new DataView(header.buffer);
  view.setUint16(0, sport, false);
  view.setUint16(2, dport, false);
  view.setUint16(4, length, false);
  const csum = internetChecksum(concat(pseudoHeader(src, finalDst, length, IPPROTO_UDP), header, payload));
  view.setUint16(6, csum === 0 ? 0xffff : csum, false);
  return concat(header, payload);
}

/** 40-byte IPv6 header + payload (traffic class and flow label 0). */
export function ipv6Packet(src: Uint8Array, dst: Uint8Array, nextHeader: number, payload: Uint8Array, hopLimit = DEFAULT_HOP_LIMIT): Uint8Array {
  if (payload.length > 0xffff) throw new RangeError('IPv6 payload needs a jumbogram');
  const header = new Uint8Array(8);
  const view = new DataView(header.buffer);
  view.setUint32(0, 6 << 28, false);
  view.setUint16(4, payload.length, false);
  header[6] = nextHeader;
  header[7] = hopLimit;
  return concat(header, src, dst, payload);
}

/**
 * IPv6 packet = header (Next Header 43) + routing header + UDP. `rh` must be exactly one
 * complete header whose Next Header byte is 17 (the only upper layer the planner builds).
 */
export function packetWithRoutingHeader(
  rh: Uint8Array,
  opts: { src: Uint8Array; dst: Uint8Array; finalDst: Uint8Array; payload: Uint8Array },
): Uint8Array {
  if (rh.length < 2 || rh.length !== (rh[1]! + 1) * 8) throw new RangeError('routing header must be exactly one header long');
  if (rh[0] !== IPPROTO_UDP) throw new RangeError(`only Next Header 17 (UDP) is built here, got ${rh[0]}`);
  const upper = udpDatagram(opts.src, opts.finalDst, opts.payload);
  return ipv6Packet(opts.src, opts.dst, IPPROTO_ROUTING, concat(rh, upper));
}

/** GPS ns -> pcap time stamp (ns since the Unix epoch). */
export function gpsToPcapNs(tGpsNs: bigint): bigint {
  const t = tGpsNs + GPS_TO_PCAP_NS;
  if (t < 0n || t > 0xffffffffn * NS_PER_S + (NS_PER_S - 1n)) throw new RangeError('time does not fit a pcap time stamp');
  return t;
}

/** A classic pcap file (nanosecond, LINKTYPE_RAW) holding the given IPv6 packets. */
export function pcapFile(frames: ReadonlyArray<{ packet: Uint8Array; tGpsNs: bigint }>): Uint8Array {
  const header = new Uint8Array(24);
  const hv = new DataView(header.buffer);
  hv.setUint32(0, PCAP_MAGIC_NS, true);
  hv.setUint16(4, 2, true);
  hv.setUint16(6, 4, true);
  hv.setInt32(8, 0, true);
  hv.setUint32(12, 0, true);
  hv.setUint32(16, DEFAULT_SNAPLEN, true);
  hv.setUint32(20, LINKTYPE_RAW, true);
  const parts: Uint8Array[] = [header];
  for (const { packet, tGpsNs } of frames) {
    if (packet.length === 0 || packet[0]! >> 4 !== 6) throw new RangeError('expected an IPv6 packet (version 6)');
    if (packet.length > DEFAULT_SNAPLEN) throw new RangeError('frame exceeds snaplen');
    const t = gpsToPcapNs(tGpsNs);
    const rec = new Uint8Array(16);
    const rv = new DataView(rec.buffer);
    rv.setUint32(0, Number(t / NS_PER_S), true);
    rv.setUint32(4, Number(t % NS_PER_S), true);
    rv.setUint32(8, packet.length, true);
    rv.setUint32(12, packet.length, true);
    parts.push(rec, packet);
  }
  return concat(...parts);
}
