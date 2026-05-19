import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary } from "../api/types";
import { resolveEvolutionHomePath } from "../app/workbenchContract";

export function LegacyEvolutionRedirect() {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  if (!configQuery.data && !configQuery.isError) {
    return null;
  }

  return <Navigate to={resolveEvolutionHomePath(configQuery.data)} replace />;
}
