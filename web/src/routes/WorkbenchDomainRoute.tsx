import { PropsWithChildren } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary } from "../api/types";
import { isWorkbenchDomainEnabled, resolveWorkbenchHomePath, WorkbenchDomain } from "../app/workbenchContract";

type WorkbenchDomainRouteProps = PropsWithChildren<{
  domain: WorkbenchDomain;
}>;

export function WorkbenchDomainRoute({ domain, children }: WorkbenchDomainRouteProps) {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  if (configQuery.data && !isWorkbenchDomainEnabled(configQuery.data, domain)) {
    return <Navigate to={resolveWorkbenchHomePath(configQuery.data)} replace />;
  }

  return <>{children}</>;
}
