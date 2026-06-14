export function ok(stdout = "", stderr = "") {
  return { code: 0, stdout, stderr };
}

export function fail(code, stderr = "", stdout = "") {
  return { code, stdout, stderr };
}
