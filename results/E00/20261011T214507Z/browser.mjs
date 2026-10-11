// experiments/E00/browser.ts
import { readFileSync, writeFileSync } from "node:fs";

// web/node_modules/satellite.js/dist/constants.js
var pi = Math.PI;
var twoPi = pi * 2;
var deg2rad = pi / 180;
var rad2deg = 180 / pi;
var minutesPerDay = 1440;
var mu = 398600.8;
var earthRadius = 6378.135;
var xke = 60 / Math.sqrt(earthRadius * earthRadius * earthRadius / mu);
var vkmpersec = earthRadius * xke / 60;
var tumin = 1 / xke;
var j2 = 1082616e-9;
var j3 = -253881e-11;
var j4 = -165597e-11;
var j3oj2 = j3 / j2;
var x2o3 = 2 / 3;
var xpdotp = 1440 / (2 * pi);

// web/node_modules/satellite.js/dist/ext.js
function days2mdhms(year, days) {
  const lmonth = [
    31,
    year % 4 === 0 ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31
  ];
  const dayofyr = Math.floor(days);
  let i = 1;
  let inttemp = 0;
  while (dayofyr > inttemp + lmonth[i - 1] && i < 12) {
    inttemp += lmonth[i - 1];
    i += 1;
  }
  const mon = i;
  const day = dayofyr - inttemp;
  let temp = (days - dayofyr) * 24;
  const hr = Math.floor(temp);
  temp = (temp - hr) * 60;
  const minute = Math.floor(temp);
  const sec = (temp - minute) * 60;
  return {
    mon,
    day,
    hr,
    minute,
    sec
  };
}
function jdayInternal(year, mon, day, hr, minute, sec, msec = 0) {
  return 367 * year - Math.floor(7 * (year + Math.floor((mon + 9) / 12)) * 0.25) + Math.floor(275 * mon / 9) + day + 17210135e-1 + ((msec / 6e4 + sec / 60 + minute) / 60 + hr) / 24;
}
function jday(yearOrDate, mon, day, hr, minute, sec, msec = 0) {
  if (yearOrDate instanceof Date) {
    const date = yearOrDate;
    return jdayInternal(
      date.getUTCFullYear(),
      date.getUTCMonth() + 1,
      // Note, this function requires months in range 1-12.
      date.getUTCDate(),
      date.getUTCHours(),
      date.getUTCMinutes(),
      date.getUTCSeconds(),
      date.getUTCMilliseconds()
    );
  }
  return jdayInternal(yearOrDate, mon, day, hr, minute, sec, msec);
}

// web/node_modules/satellite.js/dist/propagation/dpper.js
function dpper(satrec, options) {
  const { e3, ee2, peo, pgho, pho, pinco, plo, se2, se3, sgh2, sgh3, sgh4, sh2, sh3, si2, si3, sl2, sl3, sl4, t, xgh2, xgh3, xgh4, xh2, xh3, xi2, xi3, xl2, xl3, xl4, zmol, zmos } = satrec;
  const { init, opsmode } = options;
  let { ep, inclp, nodep, argpp, mp } = options;
  let alfdp;
  let betdp;
  let cosip;
  let sinip;
  let cosop;
  let sinop;
  let dalf;
  let dbet;
  let dls;
  let f2;
  let f3;
  let pe;
  let pgh;
  let ph;
  let pinc;
  let pl;
  let sinzf;
  let xls;
  let xnoh;
  let zf;
  let zm;
  const zns = 119459e-10;
  const zes = 0.01675;
  const znl = 15835218e-11;
  const zel = 0.0549;
  zm = zmos + zns * t;
  if (init === "y") {
    zm = zmos;
  }
  zf = zm + 2 * zes * Math.sin(zm);
  sinzf = Math.sin(zf);
  f2 = 0.5 * sinzf * sinzf - 0.25;
  f3 = -0.5 * sinzf * Math.cos(zf);
  const ses = se2 * f2 + se3 * f3;
  const sis = si2 * f2 + si3 * f3;
  const sls = sl2 * f2 + sl3 * f3 + sl4 * sinzf;
  const sghs = sgh2 * f2 + sgh3 * f3 + sgh4 * sinzf;
  const shs = sh2 * f2 + sh3 * f3;
  zm = zmol + znl * t;
  if (init === "y") {
    zm = zmol;
  }
  zf = zm + 2 * zel * Math.sin(zm);
  sinzf = Math.sin(zf);
  f2 = 0.5 * sinzf * sinzf - 0.25;
  f3 = -0.5 * sinzf * Math.cos(zf);
  const sel = ee2 * f2 + e3 * f3;
  const sil = xi2 * f2 + xi3 * f3;
  const sll = xl2 * f2 + xl3 * f3 + xl4 * sinzf;
  const sghl = xgh2 * f2 + xgh3 * f3 + xgh4 * sinzf;
  const shll = xh2 * f2 + xh3 * f3;
  pe = ses + sel;
  pinc = sis + sil;
  pl = sls + sll;
  pgh = sghs + sghl;
  ph = shs + shll;
  if (init === "n") {
    pe -= peo;
    pinc -= pinco;
    pl -= plo;
    pgh -= pgho;
    ph -= pho;
    inclp += pinc;
    ep += pe;
    sinip = Math.sin(inclp);
    cosip = Math.cos(inclp);
    if (inclp >= 0.2) {
      ph /= sinip;
      pgh -= cosip * ph;
      argpp += pgh;
      nodep += ph;
      mp += pl;
    } else {
      sinop = Math.sin(nodep);
      cosop = Math.cos(nodep);
      alfdp = sinip * sinop;
      betdp = sinip * cosop;
      dalf = ph * cosop + pinc * cosip * sinop;
      dbet = -ph * sinop + pinc * cosip * cosop;
      alfdp += dalf;
      betdp += dbet;
      nodep %= twoPi;
      if (nodep < 0 && opsmode === "a") {
        nodep += twoPi;
      }
      xls = mp + argpp + cosip * nodep;
      dls = pl + pgh - pinc * nodep * sinip;
      xls += dls;
      xnoh = nodep;
      nodep = Math.atan2(alfdp, betdp);
      if (nodep < 0 && opsmode === "a") {
        nodep += twoPi;
      }
      if (Math.abs(xnoh - nodep) > pi) {
        if (nodep < xnoh) {
          nodep += twoPi;
        } else {
          nodep -= twoPi;
        }
      }
      mp += pl;
      argpp = xls - mp - cosip * nodep;
    }
  }
  return {
    ep,
    inclp,
    nodep,
    argpp,
    mp
  };
}

// web/node_modules/satellite.js/dist/propagation/dscom.js
function dscom(options) {
  const { epoch, ep, argpp, tc, inclp, nodep, np } = options;
  let a1;
  let a2;
  let a3;
  let a4;
  let a5;
  let a6;
  let a7;
  let a8;
  let a9;
  let a10;
  let cc;
  let x1;
  let x2;
  let x3;
  let x4;
  let x5;
  let x6;
  let x7;
  let x8;
  let zcosg;
  let zsing;
  let zcosh;
  let zsinh;
  let zcosi;
  let zsini;
  let ss1;
  let ss2;
  let ss3;
  let ss4;
  let ss5;
  let ss6;
  let ss7;
  let sz1;
  let sz2;
  let sz3;
  let sz11;
  let sz12;
  let sz13;
  let sz21;
  let sz22;
  let sz23;
  let sz31;
  let sz32;
  let sz33;
  let s1;
  let s2;
  let s3;
  let s4;
  let s5;
  let s6;
  let s7;
  let z1;
  let z2;
  let z3;
  let z11;
  let z12;
  let z13;
  let z21;
  let z22;
  let z23;
  let z31;
  let z32;
  let z33;
  const zes = 0.01675;
  const zel = 0.0549;
  const c1ss = 29864797e-13;
  const c1l = 47968065e-14;
  const zsinis = 0.39785416;
  const zcosis = 0.91744867;
  const zcosgs = 0.1945905;
  const zsings = -0.98088458;
  const nm = np;
  const em = ep;
  const snodm = Math.sin(nodep);
  const cnodm = Math.cos(nodep);
  const sinomm = Math.sin(argpp);
  const cosomm = Math.cos(argpp);
  const sinim = Math.sin(inclp);
  const cosim = Math.cos(inclp);
  const emsq = em * em;
  const betasq = 1 - emsq;
  const rtemsq = Math.sqrt(betasq);
  const peo = 0;
  const pinco = 0;
  const plo = 0;
  const pgho = 0;
  const pho = 0;
  const day = epoch + 18261.5 + tc / 1440;
  const xnodce = (4.523602 - 92422029e-11 * day) % twoPi;
  const stem = Math.sin(xnodce);
  const ctem = Math.cos(xnodce);
  const zcosil = 0.91375164 - 0.03568096 * ctem;
  const zsinil = Math.sqrt(1 - zcosil * zcosil);
  const zsinhl = 0.089683511 * stem / zsinil;
  const zcoshl = Math.sqrt(1 - zsinhl * zsinhl);
  const gam = 5.8351514 + 1944368e-9 * day;
  let zx = 0.39785416 * stem / zsinil;
  const zy = zcoshl * ctem + 0.91744867 * zsinhl * stem;
  zx = Math.atan2(zx, zy);
  zx += gam - xnodce;
  const zcosgl = Math.cos(zx);
  const zsingl = Math.sin(zx);
  zcosg = zcosgs;
  zsing = zsings;
  zcosi = zcosis;
  zsini = zsinis;
  zcosh = cnodm;
  zsinh = snodm;
  cc = c1ss;
  const xnoi = 1 / nm;
  let lsflg = 0;
  while (lsflg < 2) {
    lsflg += 1;
    a1 = zcosg * zcosh + zsing * zcosi * zsinh;
    a3 = -zsing * zcosh + zcosg * zcosi * zsinh;
    a7 = -zcosg * zsinh + zsing * zcosi * zcosh;
    a8 = zsing * zsini;
    a9 = zsing * zsinh + zcosg * zcosi * zcosh;
    a10 = zcosg * zsini;
    a2 = cosim * a7 + sinim * a8;
    a4 = cosim * a9 + sinim * a10;
    a5 = -sinim * a7 + cosim * a8;
    a6 = -sinim * a9 + cosim * a10;
    x1 = a1 * cosomm + a2 * sinomm;
    x2 = a3 * cosomm + a4 * sinomm;
    x3 = -a1 * sinomm + a2 * cosomm;
    x4 = -a3 * sinomm + a4 * cosomm;
    x5 = a5 * sinomm;
    x6 = a6 * sinomm;
    x7 = a5 * cosomm;
    x8 = a6 * cosomm;
    z31 = 12 * x1 * x1 - 3 * x3 * x3;
    z32 = 24 * x1 * x2 - 6 * x3 * x4;
    z33 = 12 * x2 * x2 - 3 * x4 * x4;
    z1 = 3 * (a1 * a1 + a2 * a2) + z31 * emsq;
    z2 = 6 * (a1 * a3 + a2 * a4) + z32 * emsq;
    z3 = 3 * (a3 * a3 + a4 * a4) + z33 * emsq;
    z11 = -6 * a1 * a5 + emsq * (-24 * x1 * x7 - 6 * x3 * x5);
    z12 = -6 * (a1 * a6 + a3 * a5) + emsq * (-24 * (x2 * x7 + x1 * x8) + -6 * (x3 * x6 + x4 * x5));
    z13 = -6 * a3 * a6 + emsq * (-24 * x2 * x8 - 6 * x4 * x6);
    z21 = 6 * a2 * a5 + emsq * (24 * x1 * x5 - 6 * x3 * x7);
    z22 = 6 * (a4 * a5 + a2 * a6) + emsq * (24 * (x2 * x5 + x1 * x6) - 6 * (x4 * x7 + x3 * x8));
    z23 = 6 * a4 * a6 + emsq * (24 * x2 * x6 - 6 * x4 * x8);
    z1 = z1 + z1 + betasq * z31;
    z2 = z2 + z2 + betasq * z32;
    z3 = z3 + z3 + betasq * z33;
    s3 = cc * xnoi;
    s2 = -0.5 * s3 / rtemsq;
    s4 = s3 * rtemsq;
    s1 = -15 * em * s4;
    s5 = x1 * x3 + x2 * x4;
    s6 = x2 * x3 + x1 * x4;
    s7 = x2 * x4 - x1 * x3;
    if (lsflg === 1) {
      ss1 = s1;
      ss2 = s2;
      ss3 = s3;
      ss4 = s4;
      ss5 = s5;
      ss6 = s6;
      ss7 = s7;
      sz1 = z1;
      sz2 = z2;
      sz3 = z3;
      sz11 = z11;
      sz12 = z12;
      sz13 = z13;
      sz21 = z21;
      sz22 = z22;
      sz23 = z23;
      sz31 = z31;
      sz32 = z32;
      sz33 = z33;
      zcosg = zcosgl;
      zsing = zsingl;
      zcosi = zcosil;
      zsini = zsinil;
      zcosh = zcoshl * cnodm + zsinhl * snodm;
      zsinh = snodm * zcoshl - cnodm * zsinhl;
      cc = c1l;
    }
  }
  const zmol = (4.7199672 + (0.2299715 * day - gam)) % twoPi;
  const zmos = (6.2565837 + 0.017201977 * day) % twoPi;
  const se2 = 2 * ss1 * ss6;
  const se3 = 2 * ss1 * ss7;
  const si2 = 2 * ss2 * sz12;
  const si3 = 2 * ss2 * (sz13 - sz11);
  const sl2 = -2 * ss3 * sz2;
  const sl3 = -2 * ss3 * (sz3 - sz1);
  const sl4 = -2 * ss3 * (-21 - 9 * emsq) * zes;
  const sgh2 = 2 * ss4 * sz32;
  const sgh3 = 2 * ss4 * (sz33 - sz31);
  const sgh4 = -18 * ss4 * zes;
  const sh2 = -2 * ss2 * sz22;
  const sh3 = -2 * ss2 * (sz23 - sz21);
  const ee2 = 2 * s1 * s6;
  const e3 = 2 * s1 * s7;
  const xi2 = 2 * s2 * z12;
  const xi3 = 2 * s2 * (z13 - z11);
  const xl2 = -2 * s3 * z2;
  const xl3 = -2 * s3 * (z3 - z1);
  const xl4 = -2 * s3 * (-21 - 9 * emsq) * zel;
  const xgh2 = 2 * s4 * z32;
  const xgh3 = 2 * s4 * (z33 - z31);
  const xgh4 = -18 * s4 * zel;
  const xh2 = -2 * s2 * z22;
  const xh3 = -2 * s2 * (z23 - z21);
  return {
    snodm,
    cnodm,
    sinim,
    cosim,
    sinomm,
    cosomm,
    day,
    e3,
    ee2,
    em,
    emsq,
    gam,
    peo,
    pgho,
    pho,
    pinco,
    plo,
    rtemsq,
    se2,
    se3,
    sgh2,
    sgh3,
    sgh4,
    sh2,
    sh3,
    si2,
    si3,
    sl2,
    sl3,
    sl4,
    s1,
    s2,
    s3,
    s4,
    s5,
    s6,
    s7,
    ss1,
    ss2,
    ss3,
    ss4,
    ss5,
    ss6,
    ss7,
    sz1,
    sz2,
    sz3,
    sz11,
    sz12,
    sz13,
    sz21,
    sz22,
    sz23,
    sz31,
    sz32,
    sz33,
    xgh2,
    xgh3,
    xgh4,
    xh2,
    xh3,
    xi2,
    xi3,
    xl2,
    xl3,
    xl4,
    nm,
    z1,
    z2,
    z3,
    z11,
    z12,
    z13,
    z21,
    z22,
    z23,
    z31,
    z32,
    z33,
    zmol,
    zmos
  };
}

// web/node_modules/satellite.js/dist/propagation/dsinit.js
function dsinit(options) {
  const { cosim, argpo, s1, s2, s3, s4, s5, sinim, ss1, ss2, ss3, ss4, ss5, sz1, sz3, sz11, sz13, sz21, sz23, sz31, sz33, t, tc, gsto, mo, mdot, no, nodeo, nodedot, xpidot, z1, z3, z11, z13, z21, z23, z31, z33, ecco, eccsq } = options;
  let { emsq, em, argpm, inclm, mm, nm, nodem, irez, atime, d2201, d2211, d3210, d3222, d4410, d4422, d5220, d5232, d5421, d5433, dedt, didt, dmdt, dnodt, domdt, del1, del2, del3, xfact, xlamo, xli, xni } = options;
  let f220;
  let f221;
  let f311;
  let f321;
  let f322;
  let f330;
  let f441;
  let f442;
  let f522;
  let f523;
  let f542;
  let f543;
  let g200;
  let g201;
  let g211;
  let g300;
  let g310;
  let g322;
  let g410;
  let g422;
  let g520;
  let g521;
  let g532;
  let g533;
  let sini2;
  let temp;
  let temp1;
  let xno2;
  let ainv2;
  let aonv;
  let cosisq;
  let eoc;
  const q22 = 17891679e-13;
  const q31 = 21460748e-13;
  const q33 = 22123015e-14;
  const root22 = 17891679e-13;
  const root44 = 73636953e-16;
  const root54 = 21765803e-16;
  const rptim = 0.0043752690880113;
  const root32 = 37393792e-14;
  const root52 = 11428639e-14;
  const znl = 15835218e-11;
  const zns = 119459e-10;
  irez = 0;
  if (nm < 0.0052359877 && nm > 0.0034906585) {
    irez = 1;
  }
  if (nm >= 826e-5 && nm <= 924e-5 && em >= 0.5) {
    irez = 2;
  }
  const ses = ss1 * zns * ss5;
  const sis = ss2 * zns * (sz11 + sz13);
  const sls = -zns * ss3 * (sz1 + sz3 - 14 - 6 * emsq);
  const sghs = ss4 * zns * (sz31 + sz33 - 6);
  let shs = -zns * ss2 * (sz21 + sz23);
  if (inclm < 0.052359877 || inclm > pi - 0.052359877) {
    shs = 0;
  }
  if (sinim !== 0) {
    shs /= sinim;
  }
  const sgs = sghs - cosim * shs;
  dedt = ses + s1 * znl * s5;
  didt = sis + s2 * znl * (z11 + z13);
  dmdt = sls - znl * s3 * (z1 + z3 - 14 - 6 * emsq);
  const sghl = s4 * znl * (z31 + z33 - 6);
  let shll = -znl * s2 * (z21 + z23);
  if (inclm < 0.052359877 || inclm > pi - 0.052359877) {
    shll = 0;
  }
  domdt = sgs + sghl;
  dnodt = shs;
  if (sinim !== 0) {
    domdt -= cosim / sinim * shll;
    dnodt += shll / sinim;
  }
  const dndt = 0;
  const theta = (gsto + tc * rptim) % twoPi;
  em += dedt * t;
  inclm += didt * t;
  argpm += domdt * t;
  nodem += dnodt * t;
  mm += dmdt * t;
  if (irez !== 0) {
    aonv = (nm / xke) ** x2o3;
    if (irez === 2) {
      cosisq = cosim * cosim;
      const emo = em;
      em = ecco;
      const emsqo = emsq;
      emsq = eccsq;
      eoc = em * emsq;
      g201 = -0.306 - (em - 0.64) * 0.44;
      if (em <= 0.65) {
        g211 = 3.616 - 13.247 * em + 16.29 * emsq;
        g310 = -19.302 + 117.39 * em - 228.419 * emsq + 156.591 * eoc;
        g322 = -18.9068 + 109.7927 * em - 214.6334 * emsq + 146.5816 * eoc;
        g410 = -41.122 + 242.694 * em - 471.094 * emsq + 313.953 * eoc;
        g422 = -146.407 + 841.88 * em - 1629.014 * emsq + 1083.435 * eoc;
        g520 = -532.114 + 3017.977 * em - 5740.032 * emsq + 3708.276 * eoc;
      } else {
        g211 = -72.099 + 331.819 * em - 508.738 * emsq + 266.724 * eoc;
        g310 = -346.844 + 1582.851 * em - 2415.925 * emsq + 1246.113 * eoc;
        g322 = -342.585 + 1554.908 * em - 2366.899 * emsq + 1215.972 * eoc;
        g410 = -1052.797 + 4758.686 * em - 7193.992 * emsq + 3651.957 * eoc;
        g422 = -3581.69 + 16178.11 * em - 24462.77 * emsq + 12422.52 * eoc;
        if (em > 0.715) {
          g520 = -5149.66 + 29936.92 * em - 54087.36 * emsq + 31324.56 * eoc;
        } else {
          g520 = 1464.74 - 4664.75 * em + 3763.64 * emsq;
        }
      }
      if (em < 0.7) {
        g533 = -919.2277 + 4988.61 * em - 9064.77 * emsq + 5542.21 * eoc;
        g521 = -822.71072 + 4568.6173 * em - 8491.4146 * emsq + 5337.524 * eoc;
        g532 = -853.666 + 4690.25 * em - 8624.77 * emsq + 5341.4 * eoc;
      } else {
        g533 = -37995.78 + 161616.52 * em - 229838.2 * emsq + 109377.94 * eoc;
        g521 = -51752.104 + 218913.95 * em - 309468.16 * emsq + 146349.42 * eoc;
        g532 = -40023.88 + 170470.89 * em - 242699.48 * emsq + 115605.82 * eoc;
      }
      sini2 = sinim * sinim;
      f220 = 0.75 * (1 + 2 * cosim + cosisq);
      f221 = 1.5 * sini2;
      f321 = 1.875 * sinim * (1 - 2 * cosim - 3 * cosisq);
      f322 = -1.875 * sinim * (1 + 2 * cosim - 3 * cosisq);
      f441 = 35 * sini2 * f220;
      f442 = 39.375 * sini2 * sini2;
      f522 = 9.84375 * sinim * (sini2 * (1 - 2 * cosim - 5 * cosisq) + 0.33333333 * (-2 + 4 * cosim + 6 * cosisq));
      f523 = sinim * (4.92187512 * sini2 * (-2 - 4 * cosim + 10 * cosisq) + 6.56250012 * (1 + 2 * cosim - 3 * cosisq));
      f542 = 29.53125 * sinim * (2 - 8 * cosim + cosisq * (-12 + 8 * cosim + 10 * cosisq));
      f543 = 29.53125 * sinim * (-2 - 8 * cosim + cosisq * (12 + 8 * cosim - 10 * cosisq));
      xno2 = nm * nm;
      ainv2 = aonv * aonv;
      temp1 = 3 * xno2 * ainv2;
      temp = temp1 * root22;
      d2201 = temp * f220 * g201;
      d2211 = temp * f221 * g211;
      temp1 *= aonv;
      temp = temp1 * root32;
      d3210 = temp * f321 * g310;
      d3222 = temp * f322 * g322;
      temp1 *= aonv;
      temp = 2 * temp1 * root44;
      d4410 = temp * f441 * g410;
      d4422 = temp * f442 * g422;
      temp1 *= aonv;
      temp = temp1 * root52;
      d5220 = temp * f522 * g520;
      d5232 = temp * f523 * g532;
      temp = 2 * temp1 * root54;
      d5421 = temp * f542 * g521;
      d5433 = temp * f543 * g533;
      xlamo = (mo + nodeo + nodeo - (theta + theta)) % twoPi;
      xfact = mdot + dmdt + 2 * (nodedot + dnodt - rptim) - no;
      em = emo;
      emsq = emsqo;
    }
    if (irez === 1) {
      g200 = 1 + emsq * (-2.5 + 0.8125 * emsq);
      g310 = 1 + 2 * emsq;
      g300 = 1 + emsq * (-6 + 6.60937 * emsq);
      f220 = 0.75 * (1 + cosim) * (1 + cosim);
      f311 = 0.9375 * sinim * sinim * (1 + 3 * cosim) - 0.75 * (1 + cosim);
      f330 = 1 + cosim;
      f330 = 1.875 * f330 * f330 * f330;
      del1 = 3 * nm * nm * aonv * aonv;
      del2 = 2 * del1 * f220 * g200 * q22;
      del3 = 3 * del1 * f330 * g300 * q33 * aonv;
      del1 = del1 * f311 * g310 * q31 * aonv;
      xlamo = (mo + nodeo + argpo - theta) % twoPi;
      xfact = mdot + xpidot + dmdt + domdt + dnodt - (no + rptim);
    }
    xli = xlamo;
    xni = no;
    atime = 0;
    nm = no + dndt;
  }
  return {
    em,
    argpm,
    inclm,
    mm,
    nm,
    nodem,
    irez,
    atime,
    d2201,
    d2211,
    d3210,
    d3222,
    d4410,
    d4422,
    d5220,
    d5232,
    d5421,
    d5433,
    dedt,
    didt,
    dmdt,
    dndt,
    dnodt,
    domdt,
    del1,
    del2,
    del3,
    xfact,
    xlamo,
    xli,
    xni
  };
}

// web/node_modules/satellite.js/dist/propagation/gstime.js
function gstimeInternal(jdut1) {
  const tut1 = (jdut1 - 2451545) / 36525;
  let temp = -62e-7 * tut1 * tut1 * tut1 + 0.093104 * tut1 * tut1 + (876600 * 3600 + 8640184812866e-6) * tut1 + 67310.54841;
  temp = temp * deg2rad / 240 % twoPi;
  if (temp < 0) {
    temp += twoPi;
  }
  return temp;
}
function gstime(first, month, day, hour, minute, second, millisecond) {
  if (first instanceof Date) {
    return gstimeInternal(jday(first));
  }
  if (month !== void 0) {
    return gstimeInternal(
      // biome-ignore lint/style/noNonNullAssertion: overloads make sure those are non-null
      jday(first, month, day, hour, minute, second, millisecond)
    );
  }
  return gstimeInternal(first);
}

// web/node_modules/satellite.js/dist/propagation/initl.js
function initl(options) {
  const { ecco, epoch, inclo, opsmode } = options;
  let { no } = options;
  const eccsq = ecco * ecco;
  const omeosq = 1 - eccsq;
  const rteosq = Math.sqrt(omeosq);
  const cosio = Math.cos(inclo);
  const cosio2 = cosio * cosio;
  const ak = (xke / no) ** x2o3;
  const d1 = 0.75 * j2 * (3 * cosio2 - 1) / (rteosq * omeosq);
  let delPrime = d1 / (ak * ak);
  const adel = ak * (1 - delPrime * delPrime - delPrime * (1 / 3 + 134 * delPrime * delPrime / 81));
  delPrime = d1 / (adel * adel);
  no /= 1 + delPrime;
  const ao = (xke / no) ** x2o3;
  const sinio = Math.sin(inclo);
  const po = ao * omeosq;
  const con42 = 1 - 5 * cosio2;
  const con41 = -con42 - cosio2 - cosio2;
  const ainv = 1 / ao;
  const posq = po * po;
  const rp = ao * (1 - ecco);
  const method = "n";
  let gsto;
  if (opsmode === "a") {
    const ts70 = epoch - 7305;
    const ds70 = Math.floor(ts70 + 1e-8);
    const tfrac = ts70 - ds70;
    const c1 = 0.017202791694070362;
    const thgr70 = 1.7321343856509375;
    const fk5r = 5075514194322695e-30;
    const c1p2p = c1 + twoPi;
    gsto = (thgr70 + c1 * ds70 + c1p2p * tfrac + ts70 * ts70 * fk5r) % twoPi;
    if (gsto < 0) {
      gsto += twoPi;
    }
  } else {
    gsto = gstime(epoch + 24332815e-1);
  }
  return {
    no,
    method,
    ainv,
    ao,
    con41,
    con42,
    cosio,
    cosio2,
    eccsq,
    omeosq,
    posq,
    rp,
    rteosq,
    sinio,
    gsto
  };
}

// web/node_modules/satellite.js/dist/propagation/dspace.js
function dspace(options) {
  const { irez, d2201, d2211, d3210, d3222, d4410, d4422, d5220, d5232, d5421, d5433, dedt, del1, del2, del3, didt, dmdt, dnodt, domdt, argpo, argpdot, t, tc, gsto, xfact, xlamo, no } = options;
  let { atime, em, argpm, inclm, xli, mm, xni, nodem, nm } = options;
  const fasx2 = 0.13130908;
  const fasx4 = 2.8843198;
  const fasx6 = 0.37448087;
  const g22 = 5.7686396;
  const g32 = 0.95240898;
  const g44 = 1.8014998;
  const g52 = 1.050833;
  const g54 = 4.4108898;
  const rptim = 0.0043752690880113;
  const stepp = 720;
  const stepn = -720;
  const step2 = 259200;
  let delt;
  let x2li;
  let x2omi;
  let xl;
  let xldot;
  let xnddt;
  let xndt;
  let xomi;
  let dndt = 0;
  let ft = 0;
  const theta = (gsto + tc * rptim) % twoPi;
  em += dedt * t;
  inclm += didt * t;
  argpm += domdt * t;
  nodem += dnodt * t;
  mm += dmdt * t;
  if (irez !== 0) {
    if (atime === 0 || t * atime <= 0 || Math.abs(t) < Math.abs(atime)) {
      atime = 0;
      xni = no;
      xli = xlamo;
    }
    if (t > 0) {
      delt = stepp;
    } else {
      delt = stepn;
    }
    let iretn = 381;
    while (iretn === 381) {
      if (irez !== 2) {
        xndt = del1 * Math.sin(xli - fasx2) + del2 * Math.sin(2 * (xli - fasx4)) + del3 * Math.sin(3 * (xli - fasx6));
        xldot = xni + xfact;
        xnddt = del1 * Math.cos(xli - fasx2) + 2 * del2 * Math.cos(2 * (xli - fasx4)) + 3 * del3 * Math.cos(3 * (xli - fasx6));
        xnddt *= xldot;
      } else {
        xomi = argpo + argpdot * atime;
        x2omi = xomi + xomi;
        x2li = xli + xli;
        xndt = d2201 * Math.sin(x2omi + xli - g22) + d2211 * Math.sin(xli - g22) + d3210 * Math.sin(xomi + xli - g32) + d3222 * Math.sin(-xomi + xli - g32) + d4410 * Math.sin(x2omi + x2li - g44) + d4422 * Math.sin(x2li - g44) + d5220 * Math.sin(xomi + xli - g52) + d5232 * Math.sin(-xomi + xli - g52) + d5421 * Math.sin(xomi + x2li - g54) + d5433 * Math.sin(-xomi + x2li - g54);
        xldot = xni + xfact;
        xnddt = d2201 * Math.cos(x2omi + xli - g22) + d2211 * Math.cos(xli - g22) + d3210 * Math.cos(xomi + xli - g32) + d3222 * Math.cos(-xomi + xli - g32) + d5220 * Math.cos(xomi + xli - g52) + d5232 * Math.cos(-xomi + xli - g52) + 2 * (d4410 * Math.cos(x2omi + x2li - g44) + d4422 * Math.cos(x2li - g44) + d5421 * Math.cos(xomi + x2li - g54) + d5433 * Math.cos(-xomi + x2li - g54));
        xnddt *= xldot;
      }
      if (Math.abs(t - atime) >= stepp) {
        iretn = 381;
      } else {
        ft = t - atime;
        iretn = 0;
      }
      if (iretn === 381) {
        xli += xldot * delt + xndt * step2;
        xni += xndt * delt + xnddt * step2;
        atime += delt;
      }
    }
    nm = xni + xndt * ft + xnddt * ft * ft * 0.5;
    xl = xli + xldot * ft + xndt * ft * ft * 0.5;
    if (irez !== 1) {
      mm = xl - 2 * nodem + 2 * theta;
      dndt = nm - no;
    } else {
      mm = xl - nodem - argpm + theta;
      dndt = nm - no;
    }
    nm = no + dndt;
  }
  return {
    atime,
    em,
    argpm,
    inclm,
    xli,
    mm,
    xni,
    nodem,
    dndt,
    nm
  };
}

// web/node_modules/satellite.js/dist/propagation/SatRec.js
var SatRecError;
(function(SatRecError2) {
  SatRecError2[SatRecError2["None"] = 0] = "None";
  SatRecError2[SatRecError2["MeanEccentricityOutOfRange"] = 1] = "MeanEccentricityOutOfRange";
  SatRecError2[SatRecError2["MeanMotionBelowZero"] = 2] = "MeanMotionBelowZero";
  SatRecError2[SatRecError2["PerturbedEccentricityOutOfRange"] = 3] = "PerturbedEccentricityOutOfRange";
  SatRecError2[SatRecError2["SemiLatusRectumBelowZero"] = 4] = "SemiLatusRectumBelowZero";
  SatRecError2[SatRecError2["Decayed"] = 6] = "Decayed";
})(SatRecError || (SatRecError = {}));

// web/node_modules/satellite.js/dist/propagation/sgp4.js
function sgp4(satrec, tsince) {
  let coseo1;
  let sineo1;
  let cosip;
  let sinip;
  let cosisq;
  let delm;
  let delomg;
  let eo1;
  let argpm;
  let argpp;
  let su;
  let t3;
  let t4;
  let tc;
  let tem5;
  let temp;
  let tempa;
  let tempe;
  let templ;
  let inclm;
  let mm;
  let nm;
  let nodem;
  let xincp;
  let xlm;
  let mp;
  let nodep;
  const temp4 = 15e-13;
  satrec.t = tsince;
  satrec.error = SatRecError.None;
  const xmdf = satrec.mo + satrec.mdot * satrec.t;
  const argpdf = satrec.argpo + satrec.argpdot * satrec.t;
  const nodedf = satrec.nodeo + satrec.nodedot * satrec.t;
  argpm = argpdf;
  mm = xmdf;
  const t2 = satrec.t * satrec.t;
  nodem = nodedf + satrec.nodecf * t2;
  tempa = 1 - satrec.cc1 * satrec.t;
  tempe = satrec.bstar * satrec.cc4 * satrec.t;
  templ = satrec.t2cof * t2;
  if (satrec.isimp !== 1) {
    delomg = satrec.omgcof * satrec.t;
    const delmtemp = 1 + satrec.eta * Math.cos(xmdf);
    delm = satrec.xmcof * (delmtemp * delmtemp * delmtemp - satrec.delmo);
    temp = delomg + delm;
    mm = xmdf + temp;
    argpm = argpdf - temp;
    t3 = t2 * satrec.t;
    t4 = t3 * satrec.t;
    tempa = tempa - satrec.d2 * t2 - satrec.d3 * t3 - satrec.d4 * t4;
    tempe += satrec.bstar * satrec.cc5 * (Math.sin(mm) - satrec.sinmao);
    templ = templ + satrec.t3cof * t3 + t4 * (satrec.t4cof + satrec.t * satrec.t5cof);
  }
  satrec.tempa = tempa;
  nm = satrec.no;
  let em = satrec.ecco;
  inclm = satrec.inclo;
  if (satrec.method === "d") {
    tc = satrec.t;
    const dspaceOptions = {
      irez: satrec.irez,
      d2201: satrec.d2201,
      d2211: satrec.d2211,
      d3210: satrec.d3210,
      d3222: satrec.d3222,
      d4410: satrec.d4410,
      d4422: satrec.d4422,
      d5220: satrec.d5220,
      d5232: satrec.d5232,
      d5421: satrec.d5421,
      d5433: satrec.d5433,
      dedt: satrec.dedt,
      del1: satrec.del1,
      del2: satrec.del2,
      del3: satrec.del3,
      didt: satrec.didt,
      dmdt: satrec.dmdt,
      dnodt: satrec.dnodt,
      domdt: satrec.domdt,
      argpo: satrec.argpo,
      argpdot: satrec.argpdot,
      t: satrec.t,
      tc,
      gsto: satrec.gsto,
      xfact: satrec.xfact,
      xlamo: satrec.xlamo,
      no: satrec.no,
      atime: satrec.atime,
      em,
      argpm,
      inclm,
      xli: satrec.xli,
      mm,
      xni: satrec.xni,
      nodem,
      nm
    };
    const dspaceResult = dspace(dspaceOptions);
    ({ em, argpm, inclm, mm, nodem, nm } = dspaceResult);
  }
  if (nm <= 0) {
    satrec.error = SatRecError.MeanMotionBelowZero;
    return null;
  }
  const am = (xke / nm) ** x2o3 * tempa * tempa;
  nm = xke / am ** 1.5;
  em -= tempe;
  if (em >= 1 || em < -1e-3) {
    satrec.error = SatRecError.MeanEccentricityOutOfRange;
    return null;
  }
  if (em < 1e-6) {
    em = 1e-6;
  }
  mm += satrec.no * templ;
  xlm = mm + argpm + nodem;
  nodem %= twoPi;
  argpm %= twoPi;
  xlm %= twoPi;
  mm = (xlm - argpm - nodem) % twoPi;
  const meanElements = {
    am,
    em,
    im: inclm,
    Om: nodem,
    om: argpm,
    mm,
    nm
  };
  const sinim = Math.sin(inclm);
  const cosim = Math.cos(inclm);
  let ep = em;
  xincp = inclm;
  argpp = argpm;
  nodep = nodem;
  mp = mm;
  sinip = sinim;
  cosip = cosim;
  if (satrec.method === "d") {
    const dpperParameters = {
      inclo: satrec.inclo,
      init: "n",
      ep,
      inclp: xincp,
      nodep,
      argpp,
      mp,
      opsmode: satrec.operationmode
    };
    const dpperResult = dpper(satrec, dpperParameters);
    ({ ep, nodep, argpp, mp } = dpperResult);
    xincp = dpperResult.inclp;
    if (xincp < 0) {
      xincp = -xincp;
      nodep += pi;
      argpp -= pi;
    }
    if (ep < 0 || ep > 1) {
      satrec.error = SatRecError.PerturbedEccentricityOutOfRange;
      return null;
    }
  }
  if (satrec.method === "d") {
    sinip = Math.sin(xincp);
    cosip = Math.cos(xincp);
    satrec.aycof = -0.5 * j3oj2 * sinip;
    if (Math.abs(cosip + 1) > 15e-13) {
      satrec.xlcof = -0.25 * j3oj2 * sinip * (3 + 5 * cosip) / (1 + cosip);
    } else {
      satrec.xlcof = -0.25 * j3oj2 * sinip * (3 + 5 * cosip) / temp4;
    }
  }
  const axnl = ep * Math.cos(argpp);
  temp = 1 / (am * (1 - ep * ep));
  const aynl = ep * Math.sin(argpp) + temp * satrec.aycof;
  const xl = mp + argpp + nodep + temp * satrec.xlcof * axnl;
  const u = (xl - nodep) % twoPi;
  eo1 = u;
  tem5 = 9999.9;
  let ktr = 1;
  while (Math.abs(tem5) >= 1e-12 && ktr <= 10) {
    sineo1 = Math.sin(eo1);
    coseo1 = Math.cos(eo1);
    tem5 = 1 - coseo1 * axnl - sineo1 * aynl;
    tem5 = (u - aynl * coseo1 + axnl * sineo1 - eo1) / tem5;
    if (Math.abs(tem5) >= 0.95) {
      if (tem5 > 0) {
        tem5 = 0.95;
      } else {
        tem5 = -0.95;
      }
    }
    eo1 += tem5;
    ktr += 1;
  }
  const ecose = axnl * coseo1 + aynl * sineo1;
  const esine = axnl * sineo1 - aynl * coseo1;
  const el2 = axnl * axnl + aynl * aynl;
  const pl = am * (1 - el2);
  if (pl < 0) {
    satrec.error = SatRecError.SemiLatusRectumBelowZero;
    return null;
  }
  const rl = am * (1 - ecose);
  const rdotl = Math.sqrt(am) * esine / rl;
  const rvdotl = Math.sqrt(pl) / rl;
  const betal = Math.sqrt(1 - el2);
  temp = esine / (1 + betal);
  const sinu = am / rl * (sineo1 - aynl - axnl * temp);
  const cosu = am / rl * (coseo1 - axnl + aynl * temp);
  su = Math.atan2(sinu, cosu);
  const sin2u = (cosu + cosu) * sinu;
  const cos2u = 1 - 2 * sinu * sinu;
  temp = 1 / pl;
  const temp1 = 0.5 * j2 * temp;
  const temp2 = temp1 * temp;
  if (satrec.method === "d") {
    cosisq = cosip * cosip;
    satrec.con41 = 3 * cosisq - 1;
    satrec.x1mth2 = 1 - cosisq;
    satrec.x7thm1 = 7 * cosisq - 1;
  }
  const mrt = rl * (1 - 1.5 * temp2 * betal * satrec.con41) + 0.5 * temp1 * satrec.x1mth2 * cos2u;
  if (mrt < 1) {
    satrec.error = SatRecError.Decayed;
    return null;
  }
  su -= 0.25 * temp2 * satrec.x7thm1 * sin2u;
  const xnode = nodep + 1.5 * temp2 * cosip * sin2u;
  const xinc = xincp + 1.5 * temp2 * cosip * sinip * cos2u;
  const mvt = rdotl - nm * temp1 * satrec.x1mth2 * sin2u / xke;
  const rvdot = rvdotl + nm * temp1 * (satrec.x1mth2 * cos2u + 1.5 * satrec.con41) / xke;
  const sinsu = Math.sin(su);
  const cossu = Math.cos(su);
  const snod = Math.sin(xnode);
  const cnod = Math.cos(xnode);
  const sini = Math.sin(xinc);
  const cosi = Math.cos(xinc);
  const xmx = -snod * cosi;
  const xmy = cnod * cosi;
  const ux = xmx * sinsu + cnod * cossu;
  const uy = xmy * sinsu + snod * cossu;
  const uz = sini * sinsu;
  const vx = xmx * cossu - cnod * sinsu;
  const vy = xmy * cossu - snod * sinsu;
  const vz = sini * cossu;
  const r = {
    x: mrt * ux * earthRadius,
    y: mrt * uy * earthRadius,
    z: mrt * uz * earthRadius
  };
  const v = {
    x: (mvt * ux + rvdot * vx) * vkmpersec,
    y: (mvt * uy + rvdot * vy) * vkmpersec,
    z: (mvt * uz + rvdot * vz) * vkmpersec
  };
  return {
    position: r,
    velocity: v,
    meanElements
  };
}

// web/node_modules/satellite.js/dist/propagation/sgp4init.js
function sgp4init(satrecInit, options) {
  const { opsmode, satn, epoch, xbstar, xecco, xargpo, xinclo, xmo, xno, xnodeo } = options;
  let cosim;
  let sinim;
  let cc1sq;
  let cc2;
  let cc3;
  let coef;
  let coef1;
  let cosio4;
  let em;
  let emsq;
  let eeta;
  let etasq;
  let argpm;
  let nodem;
  let inclm;
  let mm;
  let nm;
  let perige;
  let pinvsq;
  let psisq;
  let qzms24;
  let s1;
  let s2;
  let s3;
  let s4;
  let s5;
  let sfour;
  let ss1;
  let ss2;
  let ss3;
  let ss4;
  let ss5;
  let sz1;
  let sz3;
  let sz11;
  let sz13;
  let sz21;
  let sz23;
  let sz31;
  let sz33;
  let tc;
  let temp;
  let temp1;
  let temp2;
  let temp3;
  let tsi;
  let xpidot;
  let xhdot1;
  let z1;
  let z3;
  let z11;
  let z13;
  let z21;
  let z23;
  let z31;
  let z33;
  const temp4 = 15e-13;
  const satrec = satrecInit;
  satrec.isimp = 0;
  satrec.method = "n";
  satrec.aycof = 0;
  satrec.con41 = 0;
  satrec.cc1 = 0;
  satrec.cc4 = 0;
  satrec.cc5 = 0;
  satrec.d2 = 0;
  satrec.d3 = 0;
  satrec.d4 = 0;
  satrec.delmo = 0;
  satrec.eta = 0;
  satrec.argpdot = 0;
  satrec.omgcof = 0;
  satrec.sinmao = 0;
  satrec.t = 0;
  satrec.t2cof = 0;
  satrec.t3cof = 0;
  satrec.t4cof = 0;
  satrec.t5cof = 0;
  satrec.x1mth2 = 0;
  satrec.x7thm1 = 0;
  satrec.mdot = 0;
  satrec.nodedot = 0;
  satrec.xlcof = 0;
  satrec.xmcof = 0;
  satrec.nodecf = 0;
  satrec.irez = 0;
  satrec.d2201 = 0;
  satrec.d2211 = 0;
  satrec.d3210 = 0;
  satrec.d3222 = 0;
  satrec.d4410 = 0;
  satrec.d4422 = 0;
  satrec.d5220 = 0;
  satrec.d5232 = 0;
  satrec.d5421 = 0;
  satrec.d5433 = 0;
  satrec.dedt = 0;
  satrec.del1 = 0;
  satrec.del2 = 0;
  satrec.del3 = 0;
  satrec.didt = 0;
  satrec.dmdt = 0;
  satrec.dnodt = 0;
  satrec.domdt = 0;
  satrec.e3 = 0;
  satrec.ee2 = 0;
  satrec.peo = 0;
  satrec.pgho = 0;
  satrec.pho = 0;
  satrec.pinco = 0;
  satrec.plo = 0;
  satrec.se2 = 0;
  satrec.se3 = 0;
  satrec.sgh2 = 0;
  satrec.sgh3 = 0;
  satrec.sgh4 = 0;
  satrec.sh2 = 0;
  satrec.sh3 = 0;
  satrec.si2 = 0;
  satrec.si3 = 0;
  satrec.sl2 = 0;
  satrec.sl3 = 0;
  satrec.sl4 = 0;
  satrec.gsto = 0;
  satrec.xfact = 0;
  satrec.xgh2 = 0;
  satrec.xgh3 = 0;
  satrec.xgh4 = 0;
  satrec.xh2 = 0;
  satrec.xh3 = 0;
  satrec.xi2 = 0;
  satrec.xi3 = 0;
  satrec.xl2 = 0;
  satrec.xl3 = 0;
  satrec.xl4 = 0;
  satrec.xlamo = 0;
  satrec.zmol = 0;
  satrec.zmos = 0;
  satrec.atime = 0;
  satrec.xli = 0;
  satrec.xni = 0;
  satrec.bstar = xbstar;
  satrec.ecco = xecco;
  satrec.argpo = xargpo;
  satrec.inclo = xinclo;
  satrec.mo = xmo;
  satrec.no = xno;
  satrec.nokozai = xno;
  satrec.nodeo = xnodeo;
  satrec.operationmode = opsmode;
  const ss = 78 / earthRadius + 1;
  const qzms2ttemp = (120 - 78) / earthRadius;
  const qzms2t = qzms2ttemp * qzms2ttemp * qzms2ttemp * qzms2ttemp;
  satrec.init = "y";
  satrec.t = 0;
  const initlOptions = {
    satn,
    ecco: satrec.ecco,
    epoch,
    inclo: satrec.inclo,
    no: satrec.no,
    method: satrec.method,
    opsmode: satrec.operationmode
  };
  const initlResult = initl(initlOptions);
  const { ao, con42, cosio, cosio2, eccsq, omeosq, posq, rp, rteosq, sinio } = initlResult;
  satrec.no = initlResult.no;
  satrec.con41 = initlResult.con41;
  satrec.gsto = initlResult.gsto;
  satrec.a = (satrec.no * tumin) ** (-2 / 3);
  satrec.alta = satrec.a * (1 + satrec.ecco) - 1;
  satrec.altp = satrec.a * (1 - satrec.ecco) - 1;
  satrec.error = 0;
  if (omeosq >= 0 || satrec.no >= 0) {
    satrec.isimp = 0;
    if (rp < 220 / earthRadius + 1) {
      satrec.isimp = 1;
    }
    sfour = ss;
    qzms24 = qzms2t;
    perige = (rp - 1) * earthRadius;
    if (perige < 156) {
      sfour = perige - 78;
      if (perige < 98) {
        sfour = 20;
      }
      const qzms24temp = (120 - sfour) / earthRadius;
      qzms24 = qzms24temp * qzms24temp * qzms24temp * qzms24temp;
      sfour = sfour / earthRadius + 1;
    }
    pinvsq = 1 / posq;
    tsi = 1 / (ao - sfour);
    satrec.eta = ao * satrec.ecco * tsi;
    etasq = satrec.eta * satrec.eta;
    eeta = satrec.ecco * satrec.eta;
    psisq = Math.abs(1 - etasq);
    coef = qzms24 * tsi ** 4;
    coef1 = coef / psisq ** 3.5;
    cc2 = coef1 * satrec.no * (ao * (1 + 1.5 * etasq + eeta * (4 + etasq)) + 0.375 * j2 * tsi / psisq * satrec.con41 * (8 + 3 * etasq * (8 + etasq)));
    satrec.cc1 = satrec.bstar * cc2;
    cc3 = 0;
    if (satrec.ecco > 1e-4) {
      cc3 = -2 * coef * tsi * j3oj2 * satrec.no * sinio / satrec.ecco;
    }
    satrec.x1mth2 = 1 - cosio2;
    satrec.cc4 = 2 * satrec.no * coef1 * ao * omeosq * (satrec.eta * (2 + 0.5 * etasq) + satrec.ecco * (0.5 + 2 * etasq) - j2 * tsi / (ao * psisq) * (-3 * satrec.con41 * (1 - 2 * eeta + etasq * (1.5 - 0.5 * eeta)) + 0.75 * satrec.x1mth2 * (2 * etasq - eeta * (1 + etasq)) * Math.cos(2 * satrec.argpo)));
    satrec.cc5 = 2 * coef1 * ao * omeosq * (1 + 2.75 * (etasq + eeta) + eeta * etasq);
    cosio4 = cosio2 * cosio2;
    temp1 = 1.5 * j2 * pinvsq * satrec.no;
    temp2 = 0.5 * temp1 * j2 * pinvsq;
    temp3 = -0.46875 * j4 * pinvsq * pinvsq * satrec.no;
    satrec.mdot = satrec.no + 0.5 * temp1 * rteosq * satrec.con41 + 0.0625 * temp2 * rteosq * (13 - 78 * cosio2 + 137 * cosio4);
    satrec.argpdot = -0.5 * temp1 * con42 + 0.0625 * temp2 * (7 - 114 * cosio2 + 395 * cosio4) + temp3 * (3 - 36 * cosio2 + 49 * cosio4);
    xhdot1 = -temp1 * cosio;
    satrec.nodedot = xhdot1 + (0.5 * temp2 * (4 - 19 * cosio2) + 2 * temp3 * (3 - 7 * cosio2)) * cosio;
    xpidot = satrec.argpdot + satrec.nodedot;
    satrec.omgcof = satrec.bstar * cc3 * Math.cos(satrec.argpo);
    satrec.xmcof = 0;
    if (satrec.ecco > 1e-4) {
      satrec.xmcof = -x2o3 * coef * satrec.bstar / eeta;
    }
    satrec.nodecf = 3.5 * omeosq * xhdot1 * satrec.cc1;
    satrec.t2cof = 1.5 * satrec.cc1;
    if (Math.abs(cosio + 1) > 15e-13) {
      satrec.xlcof = -0.25 * j3oj2 * sinio * (3 + 5 * cosio) / (1 + cosio);
    } else {
      satrec.xlcof = -0.25 * j3oj2 * sinio * (3 + 5 * cosio) / temp4;
    }
    satrec.aycof = -0.5 * j3oj2 * sinio;
    const delmotemp = 1 + satrec.eta * Math.cos(satrec.mo);
    satrec.delmo = delmotemp * delmotemp * delmotemp;
    satrec.sinmao = Math.sin(satrec.mo);
    satrec.x7thm1 = 7 * cosio2 - 1;
    if (2 * pi / satrec.no >= 225) {
      satrec.method = "d";
      satrec.isimp = 1;
      tc = 0;
      inclm = satrec.inclo;
      const dscomOptions = {
        epoch,
        ep: satrec.ecco,
        argpp: satrec.argpo,
        tc,
        inclp: satrec.inclo,
        nodep: satrec.nodeo,
        np: satrec.no,
        e3: satrec.e3,
        ee2: satrec.ee2,
        peo: satrec.peo,
        pgho: satrec.pgho,
        pho: satrec.pho,
        pinco: satrec.pinco,
        plo: satrec.plo,
        se2: satrec.se2,
        se3: satrec.se3,
        sgh2: satrec.sgh2,
        sgh3: satrec.sgh3,
        sgh4: satrec.sgh4,
        sh2: satrec.sh2,
        sh3: satrec.sh3,
        si2: satrec.si2,
        si3: satrec.si3,
        sl2: satrec.sl2,
        sl3: satrec.sl3,
        sl4: satrec.sl4,
        xgh2: satrec.xgh2,
        xgh3: satrec.xgh3,
        xgh4: satrec.xgh4,
        xh2: satrec.xh2,
        xh3: satrec.xh3,
        xi2: satrec.xi2,
        xi3: satrec.xi3,
        xl2: satrec.xl2,
        xl3: satrec.xl3,
        xl4: satrec.xl4,
        zmol: satrec.zmol,
        zmos: satrec.zmos
      };
      const dscomResult = dscom(dscomOptions);
      satrec.e3 = dscomResult.e3;
      satrec.ee2 = dscomResult.ee2;
      satrec.peo = dscomResult.peo;
      satrec.pgho = dscomResult.pgho;
      satrec.pho = dscomResult.pho;
      satrec.pinco = dscomResult.pinco;
      satrec.plo = dscomResult.plo;
      satrec.se2 = dscomResult.se2;
      satrec.se3 = dscomResult.se3;
      satrec.sgh2 = dscomResult.sgh2;
      satrec.sgh3 = dscomResult.sgh3;
      satrec.sgh4 = dscomResult.sgh4;
      satrec.sh2 = dscomResult.sh2;
      satrec.sh3 = dscomResult.sh3;
      satrec.si2 = dscomResult.si2;
      satrec.si3 = dscomResult.si3;
      satrec.sl2 = dscomResult.sl2;
      satrec.sl3 = dscomResult.sl3;
      satrec.sl4 = dscomResult.sl4;
      ({
        sinim,
        cosim,
        em,
        emsq,
        s1,
        s2,
        s3,
        s4,
        s5,
        ss1,
        ss2,
        ss3,
        ss4,
        ss5,
        sz1,
        sz3,
        sz11,
        sz13,
        sz21,
        sz23,
        sz31,
        sz33
      } = dscomResult);
      satrec.xgh2 = dscomResult.xgh2;
      satrec.xgh3 = dscomResult.xgh3;
      satrec.xgh4 = dscomResult.xgh4;
      satrec.xh2 = dscomResult.xh2;
      satrec.xh3 = dscomResult.xh3;
      satrec.xi2 = dscomResult.xi2;
      satrec.xi3 = dscomResult.xi3;
      satrec.xl2 = dscomResult.xl2;
      satrec.xl3 = dscomResult.xl3;
      satrec.xl4 = dscomResult.xl4;
      satrec.zmol = dscomResult.zmol;
      satrec.zmos = dscomResult.zmos;
      ({ nm, z1, z3, z11, z13, z21, z23, z31, z33 } = dscomResult);
      const dpperOptions = {
        inclo: inclm,
        init: satrec.init,
        ep: satrec.ecco,
        inclp: satrec.inclo,
        nodep: satrec.nodeo,
        argpp: satrec.argpo,
        mp: satrec.mo,
        opsmode: satrec.operationmode
      };
      const dpperResult = dpper(satrec, dpperOptions);
      satrec.ecco = dpperResult.ep;
      satrec.inclo = dpperResult.inclp;
      satrec.nodeo = dpperResult.nodep;
      satrec.argpo = dpperResult.argpp;
      satrec.mo = dpperResult.mp;
      argpm = 0;
      nodem = 0;
      mm = 0;
      const dsinitOptions = {
        cosim,
        emsq,
        argpo: satrec.argpo,
        s1,
        s2,
        s3,
        s4,
        s5,
        sinim,
        ss1,
        ss2,
        ss3,
        ss4,
        ss5,
        sz1,
        sz3,
        sz11,
        sz13,
        sz21,
        sz23,
        sz31,
        sz33,
        t: satrec.t,
        tc,
        gsto: satrec.gsto,
        mo: satrec.mo,
        mdot: satrec.mdot,
        no: satrec.no,
        nodeo: satrec.nodeo,
        nodedot: satrec.nodedot,
        xpidot,
        z1,
        z3,
        z11,
        z13,
        z21,
        z23,
        z31,
        z33,
        ecco: satrec.ecco,
        eccsq,
        em,
        argpm,
        inclm,
        mm,
        nm,
        nodem,
        irez: satrec.irez,
        atime: satrec.atime,
        d2201: satrec.d2201,
        d2211: satrec.d2211,
        d3210: satrec.d3210,
        d3222: satrec.d3222,
        d4410: satrec.d4410,
        d4422: satrec.d4422,
        d5220: satrec.d5220,
        d5232: satrec.d5232,
        d5421: satrec.d5421,
        d5433: satrec.d5433,
        dedt: satrec.dedt,
        didt: satrec.didt,
        dmdt: satrec.dmdt,
        dnodt: satrec.dnodt,
        domdt: satrec.domdt,
        del1: satrec.del1,
        del2: satrec.del2,
        del3: satrec.del3,
        xfact: satrec.xfact,
        xlamo: satrec.xlamo,
        xli: satrec.xli,
        xni: satrec.xni
      };
      const dsinitResult = dsinit(dsinitOptions);
      satrec.irez = dsinitResult.irez;
      satrec.atime = dsinitResult.atime;
      satrec.d2201 = dsinitResult.d2201;
      satrec.d2211 = dsinitResult.d2211;
      satrec.d3210 = dsinitResult.d3210;
      satrec.d3222 = dsinitResult.d3222;
      satrec.d4410 = dsinitResult.d4410;
      satrec.d4422 = dsinitResult.d4422;
      satrec.d5220 = dsinitResult.d5220;
      satrec.d5232 = dsinitResult.d5232;
      satrec.d5421 = dsinitResult.d5421;
      satrec.d5433 = dsinitResult.d5433;
      satrec.dedt = dsinitResult.dedt;
      satrec.didt = dsinitResult.didt;
      satrec.dmdt = dsinitResult.dmdt;
      satrec.dnodt = dsinitResult.dnodt;
      satrec.domdt = dsinitResult.domdt;
      satrec.del1 = dsinitResult.del1;
      satrec.del2 = dsinitResult.del2;
      satrec.del3 = dsinitResult.del3;
      satrec.xfact = dsinitResult.xfact;
      satrec.xlamo = dsinitResult.xlamo;
      satrec.xli = dsinitResult.xli;
      satrec.xni = dsinitResult.xni;
    }
    if (satrec.isimp !== 1) {
      cc1sq = satrec.cc1 * satrec.cc1;
      satrec.d2 = 4 * ao * tsi * cc1sq;
      temp = satrec.d2 * tsi * satrec.cc1 / 3;
      satrec.d3 = (17 * ao + sfour) * temp;
      satrec.d4 = 0.5 * temp * ao * tsi * (221 * ao + 31 * sfour) * satrec.cc1;
      satrec.t3cof = satrec.d2 + 2 * cc1sq;
      satrec.t4cof = 0.25 * (3 * satrec.d3 + satrec.cc1 * (12 * satrec.d2 + 10 * cc1sq));
      satrec.t5cof = 0.2 * (3 * satrec.d4 + 12 * satrec.cc1 * satrec.d3 + 6 * satrec.d2 * satrec.d2 + 15 * cc1sq * (2 * satrec.d2 + cc1sq));
    }
  }
  sgp4(satrec, 0);
  satrec.init = "n";
}

// web/node_modules/satellite.js/dist/io.js
function initSatrec(satrec, opsmode) {
  sgp4init(satrec, {
    opsmode,
    satn: satrec.satnum,
    epoch: satrec.jdsatepoch - 24332815e-1,
    xbstar: satrec.bstar,
    xecco: satrec.ecco,
    xargpo: satrec.argpo,
    xinclo: satrec.inclo,
    xmo: satrec.mo,
    xno: satrec.no,
    xnodeo: satrec.nodeo
  });
}
function json2satrec(jsonobj, opsmode = "i") {
  const error = 0;
  const satnum = jsonobj.NORAD_CAT_ID.toString();
  const epoch = new Date(jsonobj.EPOCH.endsWith("Z") ? jsonobj.EPOCH : `${jsonobj.EPOCH}Z`);
  const year = epoch.getUTCFullYear();
  const epochyr = Number(year.toString().slice(-2));
  const epochdays = (epoch.valueOf() - new Date(Date.UTC(year, 0, 1, 0, 0, 0)).valueOf()) / (86400 * 1e3) + 1;
  let ndot = Number(jsonobj.MEAN_MOTION_DOT);
  let nddot = Number(jsonobj.MEAN_MOTION_DDOT);
  ndot /= xpdotp * 1440;
  nddot /= xpdotp * 1440 * 1440;
  const bstar = Number(jsonobj.BSTAR);
  const inclo = Number(jsonobj.INCLINATION) * deg2rad;
  const nodeo = Number(jsonobj.RA_OF_ASC_NODE) * deg2rad;
  const ecco = Number(jsonobj.ECCENTRICITY);
  const argpo = Number(jsonobj.ARG_OF_PERICENTER) * deg2rad;
  const mo = Number(jsonobj.MEAN_ANOMALY) * deg2rad;
  const no = Number(jsonobj.MEAN_MOTION) / xpdotp;
  const mdhmsResult = days2mdhms(year, epochdays);
  const { mon, day, hr, minute, sec } = mdhmsResult;
  const jdsatepoch = jday(year, mon, day, hr, minute, sec);
  const satrec = {
    error,
    satnum,
    epochyr,
    epochdays,
    ndot,
    nddot,
    bstar,
    inclo,
    nodeo,
    ecco,
    argpo,
    mo,
    no,
    jdsatepoch
  };
  initSatrec(satrec, opsmode);
  return satrec;
}

// web/node_modules/satellite.js/dist/propagation/check-for-decay.js
var checkForDecay = (satrec) => satrec.tempa <= 0;

// web/node_modules/satellite.js/dist/propagation/propagate.js
function propagate(satrec, ...args) {
  const last = args.at(-1);
  const options = typeof last === "object" && !(last instanceof Date) ? last : void 0;
  const jdayArgs = options ? args.slice(0, -1) : args;
  const j = jday(...jdayArgs);
  const m = (j - satrec.jdsatepoch) * minutesPerDay;
  const result2 = sgp4(satrec, m);
  if (options?.communityDecayCheckEnabled && result2 && checkForDecay(satrec)) {
    satrec.error = SatRecError.Decayed;
    return null;
  }
  return result2;
}

// web/src/lib/orbit/constants.ts
var EARTH_EQUATORIAL_RADIUS_KM = 6378.137;
var WGS84_FLATTENING = 1 / 298.257223563;
var EARTH_POLAR_RADIUS_KM = EARTH_EQUATORIAL_RADIUS_KM * (1 - WGS84_FLATTENING);
var EARTH_POLAR_SCALE = 1 - WGS84_FLATTENING;
var DEG = Math.PI / 180;

// web/src/lib/orbit/frames.ts
function gmstRad(ms) {
  return gstime(new Date(ms));
}

// web/src/lib/orbit/propagate.ts
var SGP4_ERRORS = {
  1: "mean eccentricity out of range",
  2: "mean motion below zero",
  3: "perturbed eccentricity out of range",
  4: "semi-latus rectum below zero",
  6: "orbit has decayed"
};
function sgp4ErrorText(code) {
  return SGP4_ERRORS[code] ?? `SGP4 error ${code}`;
}
function initSatrecs(records) {
  const satrecs = new Array(records.length).fill(null);
  const errors = [];
  records.forEach((record, index) => {
    try {
      const satrec = json2satrec(record);
      if (satrec.error !== 0) {
        errors.push({
          index,
          norad: record.NORAD_CAT_ID,
          name: record.OBJECT_NAME,
          code: satrec.error,
          message: sgp4ErrorText(satrec.error)
        });
        return;
      }
      satrecs[index] = satrec;
    } catch (error) {
      errors.push({
        index,
        norad: record.NORAD_CAT_ID,
        name: record.OBJECT_NAME,
        code: -1,
        message: error instanceof Error ? error.message : String(error)
      });
    }
  });
  return { satrecs, errors };
}
function propagateKm(satrec, ms) {
  const state = propagate(satrec, new Date(ms));
  if (!state) return null;
  const { position: r, velocity: v } = state;
  if (!Number.isFinite(r.x) || !Number.isFinite(r.y) || !Number.isFinite(r.z)) return null;
  return { r, v };
}
function propagateAllTemeKm(satrecs, ms, out) {
  let failed = 0;
  for (let i = 0; i < satrecs.length; i += 1) {
    const satrec = satrecs[i];
    const state = satrec ? propagateKm(satrec, ms) : null;
    if (!state) {
      out[3 * i] = Number.NaN;
      out[3 * i + 1] = Number.NaN;
      out[3 * i + 2] = Number.NaN;
      if (satrec) failed += 1;
      continue;
    }
    out[3 * i] = state.r.x;
    out[3 * i + 1] = state.r.y;
    out[3 * i + 2] = state.r.z;
  }
  return failed;
}

// web/src/lib/route/geometry.ts
var WGS84_A_KM = 6378.137;
var WGS84_F = 1 / 298.257223563;
var WGS84_B_KM = WGS84_A_KM * (1 - WGS84_F);
var WGS84_E2 = WGS84_F * (2 - WGS84_F);
var INV_PHI = (Math.sqrt(5) - 1) / 2;
var DEG2RAD = Math.PI / 180;
var RAD2DEG = 180 / Math.PI;
function temeToEcef(x, y, z, gmstRad2) {
  const c = Math.cos(gmstRad2);
  const s = Math.sin(gmstRad2);
  return [c * x + s * y, -s * x + c * y, z];
}

// web/src/lib/route/frame.ts
function ecefFrameFromTeme(temeKm, ms) {
  const gmst = gmstRad(ms);
  const ecefKm = new Float64Array(temeKm.length);
  for (let i = 0; i < temeKm.length; i += 3) {
    const [x, y, z] = temeToEcef(temeKm[i], temeKm[i + 1], temeKm[i + 2], gmst);
    ecefKm[i] = x;
    ecefKm[i + 1] = y;
    ecefKm[i + 2] = z;
  }
  return { ecefKm };
}

// web/src/lib/data-types.ts
var OMM_FIELDS = [
  "OBJECT_NAME",
  "OBJECT_ID",
  "EPOCH",
  "MEAN_MOTION",
  "ECCENTRICITY",
  "INCLINATION",
  "RA_OF_ASC_NODE",
  "ARG_OF_PERICENTER",
  "MEAN_ANOMALY",
  "EPHEMERIS_TYPE",
  "CLASSIFICATION_TYPE",
  "NORAD_CAT_ID",
  "ELEMENT_SET_NO",
  "REV_AT_EPOCH",
  "BSTAR",
  "MEAN_MOTION_DOT",
  "MEAN_MOTION_DDOT",
  "RMS",
  "DATA_SOURCE"
];
var OMM_REQUIRED_FIELDS = OMM_FIELDS.filter(
  (field) => field !== "RMS" && field !== "DATA_SOURCE"
);

// web/src/lib/paths.ts
var BASE_URL = normaliseBase("/");
function normaliseBase(base) {
  const trimmed = base.replace(/^\/+|\/+$/g, "");
  return trimmed === "" ? "/" : `/${trimmed}/`;
}

// web/src/lib/data.ts
var DataContractError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "DataContractError";
  }
};
function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function ommRowsToRecords(value) {
  const where = "omm.min.json";
  if (!isObject(value)) throw new DataContractError(`${where}: not a JSON object`);
  const fields = value["fields"];
  const rows = value["rows"];
  if (!Array.isArray(fields) || !fields.every((f) => typeof f === "string")) {
    throw new DataContractError(`${where}: "fields" must be an array of strings`);
  }
  if (!Array.isArray(rows)) throw new DataContractError(`${where}: "rows" must be an array`);
  for (const required of OMM_REQUIRED_FIELDS) {
    if (!fields.includes(required)) throw new DataContractError(`${where}: missing field ${required}`);
  }
  const width = fields.length;
  return rows.map((row, index) => {
    if (!Array.isArray(row) || row.length !== width) {
      throw new DataContractError(`${where}: row ${index} must have ${width} values`);
    }
    const record = {};
    for (let i = 0; i < width; i += 1) {
      const value2 = row[i];
      if (value2 !== null) record[fields[i]] = value2;
    }
    return record;
  });
}

// web/src/engine/sizes.ts
var TCRH_FIXED_BYTES = 12;
var TCRH_ENTRY_BYTES = 3;
var TCRH_MAX_HOPS = 255;
var CRH_FIXED_BYTES = 4;
function checkCount(n, upper) {
  if (typeof n !== "number" || !Number.isSafeInteger(n)) {
    throw new TypeError(`segment count must be an integer, got ${String(n)}`);
  }
  if (n < 0) throw new RangeError(`segment count must be >= 0, got ${n}`);
  if (upper !== void 0 && n > upper) throw new RangeError(`segment count must be <= ${upper}, got ${n}`);
}
function pad8(nbytes) {
  checkCount(nbytes);
  return Math.ceil(nbytes / 8) * 8;
}
function tcrhSize(n) {
  checkCount(n, TCRH_MAX_HOPS);
  return pad8(TCRH_FIXED_BYTES + TCRH_ENTRY_BYTES * n);
}

// web/src/engine/timebase.ts
var UNIT_NS = [1e6, 1e5, 25e4, 125e3];
var MOD32 = 2 ** 32;
var HALF32 = 2 ** 31;
var MOD32_BIG = 1n << 32n;
var GPS_EPOCH_UNIX_S = Date.UTC(1980, 0, 6) / 1e3;
var OFFSET_VALID_FROM_UNIX_S = Date.UTC(2017, 0, 1) / 1e3;
function requireInt(name, value) {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw new TypeError(`${name} must be an integer, got ${String(value)}`);
  }
}
function checkRange(name, value, lo, hi) {
  requireInt(name, value);
  if (value < lo || value > hi) {
    throw new RangeError(`${name} must be in ${lo}..${hi}, got ${value}`);
  }
}
function isUnitCode(value) {
  return value === 0 || value === 1 || value === 2 || value === 3;
}
function unitNs(unitCode) {
  if (!isUnitCode(unitCode)) throw new RangeError(`unit code must be 0..3, got ${String(unitCode)}`);
  return UNIT_NS[unitCode];
}
function unitNsBig(unitCode) {
  return BigInt(unitNs(unitCode));
}
function floorDiv(a, b) {
  if (b <= 0n) throw new RangeError("divisor must be positive");
  const q = a / b;
  return a % b !== 0n && a < 0n ? q - 1n : q;
}
function ceilDiv(a, b) {
  return -floorDiv(-a, b);
}
function mod32Big(x) {
  const r = x % MOD32_BIG;
  return Number(r < 0n ? r + MOD32_BIG : r);
}
function ratioCeilDiv(r, divisor) {
  return ceilDiv(r.num, r.den * divisor);
}
function epochBaseAtIngress(tGpsNs, unitCode) {
  return mod32Big(ceilDiv(tGpsNs, unitNsBig(unitCode)));
}
function serialDiff(a, b) {
  requireInt("a", a);
  requireInt("b", b);
  const x = a - b + HALF32;
  return (x % MOD32 + MOD32) % MOD32 - HALF32;
}

// web/src/engine/tcrh.ts
var ROUTING_TYPE_TCRH = 253;
var MAX_HOPS = TCRH_MAX_HOPS;
var MAX_DELTA = 255;
var DEFAULT_NEXT_HEADER = 17;
var OFF_NEXT_HEADER = 0;
var OFF_HDR_EXT_LEN = 1;
var OFF_ROUTING_TYPE = 2;
var OFF_SEGMENTS_LEFT = 3;
var OFF_FLAGS = 4;
var OFF_NUM_HOPS = 5;
var OFF_DEV_HOP = 6;
var OFF_RESERVED = 7;
var OFF_EPOCH_BASE = 8;
var OFF_ENTRIES = TCRH_FIXED_BYTES;
var FLAG_DEV = 1;
var FLAG_GREEDY = 2;
var FLAG_SAT = 4;
var FLAG_UNIT_SHIFT = 4;
var FLAG_STATE_MASK = FLAG_DEV | FLAG_GREEDY | FLAG_SAT;
var SID_RESERVED = 65535;
var POLICIES = ["greedy", "continue", "drop"];
var TcrhDecodeError = class extends Error {
  reason;
  /** Offset of the offending field inside the routing header (ICMPv6 pointer), or null. */
  pointer;
  constructor(reason, message, pointer = null) {
    super(message);
    this.name = "TcrhDecodeError";
    this.reason = reason;
    this.pointer = pointer;
  }
};
function makeHeader(h) {
  checkRange("next_header", h.nextHeader, 0, 255);
  checkRange("num_hops", h.numHops, 1, MAX_HOPS);
  checkRange("segments_left", h.segmentsLeft, 0, h.numHops);
  checkRange("flags", h.flags, 0, 255);
  checkRange("dev_hop", h.devHop, 0, 255);
  checkRange("epoch_base", h.epochBase, 0, MOD32 - 1);
  if (h.sidsRev.length !== h.numHops || h.deltasRev.length !== h.numHops) {
    throw new RangeError(`num_hops=${h.numHops} but ${h.sidsRev.length} SIDs and ${h.deltasRev.length} deltas`);
  }
  for (const sid of h.sidsRev) checkRange("SID", sid, 0, 65535);
  for (const d of h.deltasRev) checkRange("delta", d, 0, MAX_DELTA);
  return Object.freeze({
    nextHeader: h.nextHeader,
    segmentsLeft: h.segmentsLeft,
    flags: h.flags,
    numHops: h.numHops,
    devHop: h.devHop,
    epochBase: h.epochBase,
    sidsRev: Object.freeze([...h.sidsRev]),
    deltasRev: Object.freeze([...h.deltasRev])
  });
}
function fromForward(sidsFwd, deltasFwd, epochBase, unitCode, nextHeader = DEFAULT_NEXT_HEADER, extraFlags = 0) {
  if (sidsFwd.length !== deltasFwd.length) {
    throw new RangeError("every hop needs exactly one delta (sidsFwd and deltasFwd differ in length)");
  }
  if (sidsFwd.length < 1 || sidsFwd.length > MAX_HOPS) {
    throw new RangeError(`a T-CRH carries 1..${MAX_HOPS} hops, got ${sidsFwd.length}`);
  }
  for (const sid of sidsFwd) checkRange("SID", sid, 0, SID_RESERVED - 1);
  for (const d of deltasFwd) checkRange("delta", d, 0, MAX_DELTA);
  checkRange("epoch_base", epochBase, 0, MOD32 - 1);
  unitNs(unitCode);
  checkRange("extra_flags", extraFlags, 0, 255);
  if ((extraFlags & ~FLAG_STATE_MASK) !== 0) {
    throw new RangeError("extra_flags may only contain DEV/GREEDY/SAT; the unit goes in unitCode");
  }
  const h = sidsFwd.length;
  return makeHeader({
    nextHeader,
    segmentsLeft: h,
    flags: unitCode << FLAG_UNIT_SHIFT | extraFlags,
    numHops: h,
    devHop: 0,
    epochBase,
    sidsRev: [...sidsFwd].reverse(),
    deltasRev: [...deltasFwd].reverse()
  });
}
function sizeOf(h) {
  return tcrhSize(h.numHops);
}
function encode(h) {
  const size = sizeOf(h);
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  view.setUint8(OFF_NEXT_HEADER, h.nextHeader);
  view.setUint8(OFF_HDR_EXT_LEN, size / 8 - 1);
  view.setUint8(OFF_ROUTING_TYPE, ROUTING_TYPE_TCRH);
  view.setUint8(OFF_SEGMENTS_LEFT, h.segmentsLeft);
  view.setUint8(OFF_FLAGS, h.flags);
  view.setUint8(OFF_NUM_HOPS, h.numHops);
  view.setUint8(OFF_DEV_HOP, h.devHop);
  view.setUint8(OFF_RESERVED, 0);
  view.setUint32(OFF_EPOCH_BASE, h.epochBase, false);
  let off = OFF_ENTRIES;
  for (let i = 0; i < h.numHops; i += 1) {
    view.setUint16(off, h.sidsRev[i] ?? 0, false);
    view.setUint8(off + 2, h.deltasRev[i] ?? 0);
    off += TCRH_ENTRY_BYTES;
  }
  return out;
}
function parse(raw, exact) {
  if (raw.length < 8) throw new TcrhDecodeError("truncated", `T-CRH needs at least 8 bytes, got ${raw.length}`);
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const nextHeader = view.getUint8(OFF_NEXT_HEADER);
  const hel = view.getUint8(OFF_HDR_EXT_LEN);
  const rtype = view.getUint8(OFF_ROUTING_TYPE);
  const sl = view.getUint8(OFF_SEGMENTS_LEFT);
  const flags = view.getUint8(OFF_FLAGS);
  const nhops = view.getUint8(OFF_NUM_HOPS);
  const devHop = view.getUint8(OFF_DEV_HOP);
  if (rtype !== ROUTING_TYPE_TCRH) {
    throw new TcrhDecodeError("wrong_type", `routing type ${rtype} is not T-CRH (${ROUTING_TYPE_TCRH})`, OFF_ROUTING_TYPE);
  }
  if (nhops === 0) {
    throw new TcrhDecodeError("numhops_zero", "Num Hops is 0 (a T-CRH carries 1..255 entries)", OFF_NUM_HOPS);
  }
  if (sl > nhops) {
    throw new TcrhDecodeError("sl_gt_numhops", `Segments Left ${sl} > Num Hops ${nhops}`, OFF_SEGMENTS_LEFT);
  }
  const total = (hel + 1) * 8;
  const need = tcrhSize(nhops);
  if (total < need) {
    throw new TcrhDecodeError(
      "length_mismatch",
      `Hdr Ext Len ${hel} gives ${total} bytes, but ${nhops} hops need ${need}`,
      OFF_HDR_EXT_LEN
    );
  }
  if (raw.length < total) {
    throw new TcrhDecodeError("truncated", `Hdr Ext Len announces ${total} bytes, only ${raw.length} present`);
  }
  if (exact && raw.length !== total) {
    throw new TcrhDecodeError("trailing_bytes", `Hdr Ext Len announces ${total} bytes, got ${raw.length}`);
  }
  const epochBase = view.getUint32(OFF_EPOCH_BASE, false);
  const sidsRev = [];
  const deltasRev = [];
  let off = OFF_ENTRIES;
  for (let i = 0; i < nhops; i += 1) {
    sidsRev.push(view.getUint16(off, false));
    deltasRev.push(view.getUint8(off + 2));
    off += TCRH_ENTRY_BYTES;
  }
  const header = makeHeader({ nextHeader, segmentsLeft: sl, flags, numHops: nhops, devHop, epochBase, sidsRev, deltasRev });
  return { header, length: total };
}
var isGreedy = (h) => (h.flags & FLAG_GREEDY) !== 0;
function deadline(h, k) {
  checkRange("hop index k", k, 1, h.numHops);
  let sum = h.epochBase;
  for (let i = h.numHops - k; i < h.numHops; i += 1) sum += h.deltasRev[i] ?? 0;
  return sum % MOD32;
}
function currentHopIndex(h) {
  return h.numHops - h.segmentsLeft;
}
function currentDeadline(h) {
  const k = currentHopIndex(h);
  return k >= 1 ? deadline(h, k) : null;
}
function asRatio(b) {
  if (typeof b === "bigint") return { num: b, den: 1n };
  if (typeof b === "object" && b !== null && typeof b.num === "bigint" && typeof b.den === "bigint" && b.den > 0n) return b;
  throw new TypeError("budgets must be bigint nanoseconds or an exact Ratio (never a float)");
}
function encodeDeltas(cumulativeBudgetsNs, unitCode) {
  const u = unitNsBig(unitCode);
  const deltas = [];
  let sat = false;
  let encoded = 0n;
  for (const budget of cumulativeBudgetsNs) {
    const b = asRatio(budget);
    if (b.num < 0n) throw new RangeError("a cumulative budget cannot be negative");
    const target = ratioCeilDiv(b, u);
    let d = target - encoded;
    if (d > BigInt(MAX_DELTA)) {
      d = BigInt(MAX_DELTA);
      sat = true;
    }
    if (d < 0n) d = 0n;
    encoded += d;
    deltas.push(Number(d));
  }
  return { deltas, sat };
}
function buildHeader(sidsFwd, cumulativeBudgetsNs, tIngressGpsNs, unitCode, nextHeader = DEFAULT_NEXT_HEADER) {
  if (sidsFwd.length !== cumulativeBudgetsNs.length) {
    throw new RangeError("every hop needs exactly one cumulative budget");
  }
  const { deltas, sat } = encodeDeltas(cumulativeBudgetsNs, unitCode);
  const epoch = epochBaseAtIngress(tIngressGpsNs, unitCode);
  return fromForward(sidsFwd, deltas, epoch, unitCode, nextHeader, sat ? FLAG_SAT : 0);
}
function patch(raw, segmentsLeft, flags, devHop) {
  const out = raw.slice();
  out[OFF_SEGMENTS_LEFT] = segmentsLeft;
  out[OFF_FLAGS] = flags;
  out[OFF_DEV_HOP] = devHop;
  return out;
}
function malformed(error) {
  return result({
    action: "drop_malformed",
    reason: error.reason,
    icmpCode: error.pointer !== null ? 0 : null,
    icmpPointer: error.pointer
  });
}
function result(fields) {
  return {
    nextSid: null,
    outBytes: null,
    late: false,
    hopIndex: null,
    deadlineU: null,
    reason: null,
    icmpCode: null,
    icmpPointer: null,
    ...fields
  };
}
function processAtNode(raw, nowU, policy = "greedy") {
  if (!POLICIES.includes(policy)) throw new RangeError(`policy must be one of ${POLICIES.join(", ")}, got ${String(policy)}`);
  checkRange("now_u", nowU, 0, MOD32 - 1);
  let hdr;
  try {
    hdr = parse(raw, false).header;
  } catch (error) {
    if (!(error instanceof TcrhDecodeError)) throw error;
    if (error.reason === "wrong_type" && raw[OFF_SEGMENTS_LEFT] === 0) {
      return result({ action: "ignore", outBytes: raw.slice(), reason: error.reason });
    }
    return malformed(error);
  }
  let sl = hdr.segmentsLeft;
  let flags = hdr.flags;
  let devHop = hdr.devHop;
  const k = currentHopIndex(hdr);
  const deadlineU = currentDeadline(hdr);
  let late = false;
  if ((flags & FLAG_DEV) === 0 && sl < hdr.numHops && deadlineU !== null) {
    if (serialDiff(nowU, deadlineU) > 0) {
      late = true;
      flags |= FLAG_DEV;
      devHop = k;
    }
  }
  const common = { late, hopIndex: k, deadlineU };
  if (sl === 0) {
    return result({ action: "deliver", outBytes: patch(raw, sl, flags, devHop), ...common });
  }
  if ((flags & FLAG_DEV) !== 0) {
    if (policy === "greedy") {
      flags |= FLAG_GREEDY;
      return result({
        action: "fallback",
        nextSid: hdr.sidsRev[0] ?? null,
        outBytes: patch(raw, 0, flags, devHop),
        ...common
      });
    }
    if (policy === "drop") {
      return result({ action: "drop_late", reason: "late_strict", ...common });
    }
  }
  sl -= 1;
  const nextSid = hdr.sidsRev[sl] ?? null;
  return result({ action: "forward", nextSid, outBytes: patch(raw, sl, flags, devHop), ...common });
}
function linkDownFallback(raw) {
  let hdr;
  try {
    hdr = parse(raw, false).header;
  } catch (error) {
    if (!(error instanceof TcrhDecodeError)) throw error;
    return malformed(error);
  }
  if (hdr.segmentsLeft >= hdr.numHops) {
    throw new RangeError(
      `linkDownFallback needs the bytes as they leave step 5 (SL < NumHops), got SL=${hdr.segmentsLeft} NumHops=${hdr.numHops}`
    );
  }
  if (isGreedy(hdr)) throw new RangeError("a GREEDY packet is already in fallback mode; it skips dead links itself");
  const k = hdr.numHops - hdr.segmentsLeft - 1;
  let flags = hdr.flags;
  let devHop = hdr.devHop;
  if ((flags & FLAG_DEV) === 0) {
    flags |= FLAG_DEV;
    devHop = k;
  }
  flags |= FLAG_GREEDY;
  return result({
    action: "fallback",
    nextSid: hdr.sidsRev[0] ?? null,
    outBytes: patch(raw, 0, flags, devHop),
    hopIndex: k,
    reason: "link_down"
  });
}
function ingressSend(raw) {
  const hdr = parse(raw, false).header;
  if (hdr.segmentsLeft !== hdr.numHops) {
    throw new RangeError(
      `ingress expects a fresh header (SL == NumHops >= 1), got SL=${hdr.segmentsLeft} NumHops=${hdr.numHops}`
    );
  }
  const sl = hdr.segmentsLeft - 1;
  return { outBytes: patch(raw, sl, hdr.flags, hdr.devHop), firstSid: hdr.sidsRev[sl] ?? 0 };
}
function hexToBytes(hex) {
  const clean = hex.replace(/\s+/g, "");
  if (clean.length % 2 !== 0) throw new SyntaxError("hex text must have an even number of digits");
  if (/[^0-9a-fA-F]/.test(clean)) throw new SyntaxError("hex text may only contain 0-9 and a-f");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = Number.parseInt(clean.slice(2 * i, 2 * i + 2), 16);
  return out;
}
function bytesToHex(bytes, separator = "") {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(separator);
}

// web/src/engine/crh.ts
var ROUTING_TYPE_CRH16 = 5;
var ROUTING_TYPE_CRH32 = 6;
var DEFAULT_NEXT_HEADER2 = 17;
var MAX_HEADER_BYTES = (255 + 1) * 8;
var OFF_HDR_EXT_LEN2 = 1;
var OFF_ROUTING_TYPE2 = 2;
var OFF_SEGMENTS_LEFT2 = 3;
var OFF_SIDS = CRH_FIXED_BYTES;
var ICMP_CODE_ERRONEOUS_FIELD = 0;
var ICMP_CODE_MIN_LENGTH = 6;
function isCrhRoutingType(value) {
  return value === ROUTING_TYPE_CRH16 || value === ROUTING_TYPE_CRH32;
}
function sidBytes(routingType) {
  if (routingType === ROUTING_TYPE_CRH16) return 2;
  if (routingType === ROUTING_TYPE_CRH32) return 4;
  throw new RangeError(`CRH routing type must be 5 (CRH-16) or 6 (CRH-32), got ${routingType}`);
}
var CrhDecodeError = class extends Error {
  reason;
  pointer;
  constructor(reason, message, pointer = null) {
    super(message);
    this.name = "CrhDecodeError";
    this.reason = reason;
    this.pointer = pointer;
  }
};
function minHdrExtLen(segmentsLeft, routingType) {
  checkRange("segments_left", segmentsLeft, 0, 255);
  const [firstWord, perWord] = sidBytes(routingType) === 2 ? [2, 4] : [1, 2];
  if (segmentsLeft <= firstWord) return 0;
  return Math.ceil((segmentsLeft - firstWord) / perWord);
}
function crhSizeOf(h) {
  return pad8(CRH_FIXED_BYTES + sidBytes(h.routingType) * h.sidsRev.length);
}
function crhHdrExtLenOf(h) {
  return crhSizeOf(h) / 8 - 1;
}
function makeCrh(h) {
  sidBytes(h.routingType);
  checkRange("next_header", h.nextHeader, 0, 255);
  checkRange("segments_left", h.segmentsLeft, 0, 255);
  const top = h.routingType === ROUTING_TYPE_CRH16 ? 65535 : 4294967295;
  for (const sid of h.sidsRev) checkRange("SID", sid, 0, top);
  const header = Object.freeze({ ...h, sidsRev: Object.freeze([...h.sidsRev]) });
  if (crhSizeOf(header) > MAX_HEADER_BYTES) {
    throw new RangeError(`${h.sidsRev.length} SIDs do not fit in a ${MAX_HEADER_BYTES}-byte header`);
  }
  return header;
}
function crhFromForward(sidsFwd, routingType = ROUTING_TYPE_CRH16, nextHeader = DEFAULT_NEXT_HEADER2) {
  if (sidsFwd.length < 1 || sidsFwd.length > 255) {
    throw new RangeError(`a CRH path has 1..255 SIDs (Segments Left is one byte), got ${sidsFwd.length}`);
  }
  return makeCrh({ routingType, nextHeader, segmentsLeft: sidsFwd.length, sidsRev: [...sidsFwd].reverse() });
}
function encodeCrh(h) {
  const size = crhSizeOf(h);
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  view.setUint8(0, h.nextHeader);
  view.setUint8(OFF_HDR_EXT_LEN2, size / 8 - 1);
  view.setUint8(OFF_ROUTING_TYPE2, h.routingType);
  view.setUint8(OFF_SEGMENTS_LEFT2, h.segmentsLeft);
  const step = sidBytes(h.routingType);
  let off = OFF_SIDS;
  for (const sid of h.sidsRev) {
    if (step === 2) view.setUint16(off, sid, false);
    else view.setUint32(off, sid, false);
    off += step;
  }
  return out;
}
function parseCrh(raw, exact) {
  if (raw.length < 8) throw new CrhDecodeError("truncated", `a CRH is at least 8 bytes, got ${raw.length}`);
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const nextHeader = view.getUint8(0);
  const hel = view.getUint8(OFF_HDR_EXT_LEN2);
  const rtype = view.getUint8(OFF_ROUTING_TYPE2);
  const sl = view.getUint8(OFF_SEGMENTS_LEFT2);
  if (!isCrhRoutingType(rtype)) {
    throw new CrhDecodeError("wrong_type", `routing type ${rtype} is not CRH-16 (5) or CRH-32 (6)`, OFF_ROUTING_TYPE2);
  }
  const total = (hel + 1) * 8;
  if (raw.length < total) {
    throw new CrhDecodeError("truncated", `Hdr Ext Len announces ${total} bytes, only ${raw.length} present`);
  }
  if (exact && raw.length !== total) {
    throw new CrhDecodeError("trailing_bytes", `Hdr Ext Len announces ${total} bytes, got ${raw.length}`);
  }
  const step = sidBytes(rtype);
  const sids = [];
  for (let off = OFF_SIDS; off < total; off += step) {
    sids.push(step === 2 ? view.getUint16(off, false) : view.getUint32(off, false));
  }
  return { header: makeCrh({ routingType: rtype, nextHeader, segmentsLeft: sl, sidsRev: sids }), length: total };
}
function crhProcessAtNode(raw) {
  const empty = { nextSid: null, outBytes: null, reason: null, icmpCode: null, icmpPointer: null };
  let hdr;
  try {
    hdr = parseCrh(raw, false).header;
  } catch (error) {
    if (!(error instanceof CrhDecodeError)) throw error;
    if (error.reason === "wrong_type" && raw[OFF_SEGMENTS_LEFT2] === 0) {
      return { ...empty, action: "ignore", outBytes: raw.slice(), reason: error.reason };
    }
    return {
      ...empty,
      action: "drop_malformed",
      reason: error.reason,
      icmpCode: error.pointer !== null ? ICMP_CODE_ERRONEOUS_FIELD : null,
      icmpPointer: error.pointer
    };
  }
  if (hdr.segmentsLeft === 0) return { ...empty, action: "deliver", outBytes: raw.slice() };
  if (minHdrExtLen(hdr.segmentsLeft, hdr.routingType) > crhHdrExtLenOf(hdr)) {
    return {
      ...empty,
      action: "drop_malformed",
      reason: "min_length",
      icmpCode: ICMP_CODE_MIN_LENGTH,
      icmpPointer: OFF_SEGMENTS_LEFT2
    };
  }
  const sl = hdr.segmentsLeft - 1;
  const out = raw.slice();
  out[OFF_SEGMENTS_LEFT2] = sl;
  return { ...empty, action: "forward", nextSid: hdr.sidsRev[sl] ?? null, outBytes: out };
}

// experiments/E00/browser.ts
var input = JSON.parse(readFileSync(process.argv[2], "utf8"));
var cases = input.cases.map((c) => {
  let result2;
  if (c.op === "CE") {
    result2 = { hex: bytesToHex(encodeCrh(crhFromForward(c.sids, c.routing_type, c.nh))) };
  } else if (c.op === "CP") {
    const r = crhProcessAtNode(hexToBytes(c.hex));
    result2 = {
      action: r.action,
      next_sid: r.nextSid,
      hex: r.outBytes ? bytesToHex(r.outBytes) : null,
      reason: r.reason,
      icmp_code: r.icmpCode,
      icmp_pointer: r.icmpPointer
    };
  } else if (c.op === "B") {
    const h = buildHeader(c.sids, c.budgets.map(BigInt), BigInt(c.t), c.unit, c.nh);
    result2 = { hex: bytesToHex(encode(h)) };
  } else if (c.op === "E") {
    let deltas = c.deltas;
    let flags = c.flags;
    if (c.budgets) {
      const encoded = encodeDeltas(c.budgets.map(BigInt), c.unit);
      deltas = encoded.deltas;
      if (encoded.sat) flags |= FLAG_SAT;
    }
    result2 = { hex: bytesToHex(encode(fromForward(c.sids, deltas, c.epoch, c.unit, c.nh, flags))) };
  } else if (c.op === "I") {
    const r = ingressSend(hexToBytes(c.hex));
    result2 = { hex: bytesToHex(r.outBytes), first_sid: r.firstSid };
  } else {
    const r = c.op === "L" ? linkDownFallback(hexToBytes(c.hex)) : processAtNode(hexToBytes(c.hex), c.now, c.policy);
    result2 = {
      action: r.action,
      next_sid: r.nextSid,
      hex: r.outBytes ? bytesToHex(r.outBytes) : null,
      late: r.late,
      hop_index: r.hopIndex,
      deadline_u: r.deadlineU,
      reason: r.reason,
      icmp_code: r.icmpCode,
      icmp_pointer: r.icmpPointer
    };
  }
  return { id: c.id, ...result2 };
});
var orbits = input.orbits.map((o) => {
  const sources = { pinned: o.records, exported: ommRowsToRecords(o.omm_min) };
  const outputs = {};
  for (const [source, records] of Object.entries(sources)) {
    const { satrecs, errors } = initSatrecs(records);
    if (errors.length) throw new Error(JSON.stringify(errors));
    outputs[source] = o.times_ns.map((t) => {
      const ms = Number(BigInt(t) / 1000000n);
      const teme = new Float64Array(satrecs.length * 3);
      const failed = propagateAllTemeKm(satrecs, ms, teme);
      if (failed) throw new Error(`SGP4 failed for ${failed} satellites`);
      const ecef = ecefFrameFromTeme(teme, ms).ecefKm;
      if (![...ecef].every(Number.isFinite)) throw new Error("nonfinite ECEF");
      return Array.from({ length: satrecs.length }, (_, i) => [...ecef.slice(3 * i, 3 * i + 3)]);
    });
  }
  return { constellation: o.constellation, norads: o.records.map((r) => r.NORAD_CAT_ID), ...outputs };
});
writeFileSync(process.argv[3], JSON.stringify({ cases, orbits }) + "\n");
