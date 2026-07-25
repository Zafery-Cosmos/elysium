/** Concatène des classes conditionnelles sans dépendance externe. */
export function cx(
  ...parts: Array<string | false | null | undefined>
): string {
  return parts.filter(Boolean).join(" ");
}
