import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary } from "../api/types";
import { resolveWorkbenchHomePath } from "../app/workbenchContract";

export function HomeRedirect() {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  if (configQuery.isPending && !configQuery.data) {
    return null;
  }

  return <Navigate to={resolveWorkbenchHomePath(configQuery.data)} replace />;
}
