export function pyRound(value, ndigits = 0) {
  const factor = 10 ** ndigits;
  const scaled = value * factor;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;

  let rounded;
  if (diff < 0.5) {
    rounded = floor;
  } else if (diff > 0.5) {
    rounded = floor + 1;
  } else {
    rounded = floor % 2 === 0 ? floor : floor + 1;
  }

  const result = rounded / factor;
  return ndigits === 0 ? Object.is(result, -0) ? 0 : result : Number(result.toFixed(ndigits));
}

export function snap10(value) {
  return pyRound(Number(value) / 10) * 10;
}
