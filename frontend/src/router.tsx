import { createBrowserRouter, Navigate } from "react-router-dom";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppLayout } from "@/components/layout/AppLayout";
import AlertConfigPlaceholder from "@/pages/AlertConfigPlaceholder";
import AssetPage from "@/pages/AssetPage";
import BudgetPlaceholder from "@/pages/BudgetPlaceholder";
import CloudAccountPlaceholder from "@/pages/CloudAccountPlaceholder";
import DashboardPage from "@/pages/DashboardPage";
import EventPage from "@/pages/EventPage";
import GovernancePage from "@/pages/GovernancePage";
import LoginPage from "@/pages/LoginPage";
import ProjectSettlementPage from "@/pages/ProjectSettlementPage";
import { DEFAULT_PATH } from "@/nav/menu";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to={DEFAULT_PATH} replace /> },
      { path: "/dashboard", element: <DashboardPage /> },
      { path: "/finance/project-settlement", element: <ProjectSettlementPage /> },
      { path: "/budget", element: <BudgetPlaceholder /> },
      { path: "/governance", element: <GovernancePage /> },
      { path: "/asset", element: <AssetPage /> },
      { path: "/cloud-account", element: <CloudAccountPlaceholder /> },
      { path: "/event", element: <EventPage /> },
      { path: "/alert-config", element: <AlertConfigPlaceholder /> },
      { path: "*", element: <Navigate to={DEFAULT_PATH} replace /> },
    ],
  },
]);
