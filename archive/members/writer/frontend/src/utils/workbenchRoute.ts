type RouteQueryValue = string | number | null | undefined | Array<string | number | null | undefined>

export type WorkbenchRouteQuery = Record<string, RouteQueryValue>

export function workbenchSessionRouteQuery(
  query: WorkbenchRouteQuery,
  sessionId: string | null | undefined,
): WorkbenchRouteQuery {
  const next = { ...query }
  if (sessionId) next.session = sessionId
  else delete next.session
  return next
}
