import {
  FolderGit2,
  FolderTree,
  LayoutDashboard,
  type LucideIcon,
  MessagesSquare,
  Search,
  Settings,
  Upload,
} from "lucide-react";
import type { Route } from "next";

/**
 * The single navigation manifest, shared by the sidebar and the command palette.
 *
 * `href` is present only once the route actually exists. Because `typedRoutes`
 * validates `Route` against the files under `src/app`, adding an href for a
 * page that has not been built yet is a compile error rather than a dead link
 * a user discovers at runtime. `phase` is display metadata for the roadmap.
 */
export interface NavItem {
  label: string;
  icon: LucideIcon;
  phase: number;
  href?: Route;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", icon: LayoutDashboard, phase: 1, href: "/" },
  { label: "Search", icon: Search, phase: 6 },
  { label: "Chat", icon: MessagesSquare, phase: 7 },
  { label: "Documents", icon: Upload, phase: 3, href: "/documents" },
  { label: "Collections", icon: FolderTree, phase: 3 },
  { label: "Repositories", icon: FolderGit2, phase: 9 },
  { label: "Settings", icon: Settings, phase: 2, href: "/settings" },
];
