/** Public presentation configuration, never an authorization grant or a fallback selector. */
export function configuredCourseId(): string | null {
  const id = String(import.meta.env.VITE_COURSE_KB_ID ?? '').trim().toLowerCase()
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id) ? id : null
}
