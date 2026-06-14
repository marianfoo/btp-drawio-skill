export function pyRound(value, ndigits = 0) {
  const factor = 10 ** ndigits;
  const scaled = value * factor;
  const sign = Math.sign(scaled) || 1;
  const abs = Math.abs(scaled);
  const floor = Math.floor(abs);
  const diff = abs - floor;
  const epsilon = 1e-12;

  let rounded;
  if (Math.abs(diff - 0.5) <= epsilon) {
    rounded = floor % 2 === 0 ? floor : floor + 1;
  } else {
    rounded = Math.round(abs);
  }

  const result = (sign * rounded) / factor;
  return ndigits === 0 ? Object.is(result, -0) ? 0 : result : Number(result.toFixed(ndigits));
}

export function snap10(value) {
  return pyRound(Number(value) / 10) * 10;
}
