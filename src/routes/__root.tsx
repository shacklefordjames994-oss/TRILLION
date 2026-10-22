import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import {
  HeadContent,
  Outlet,
  Scripts,
  createRootRouteWithContext,
} from "@tanstack/react-router"
import type { ReactNode } from "react"
import { AuthProvider } from "@/lib/auth/provider"
import { AppErrorComponent } from "@/lib/error-component"
import { PreviewHostBridge } from "@/components/preview-host-bridge"
import appCss from "../styles.css?url"

const queryClient = new QueryClient()

export const Route = createRootRouteWithContext()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "OMEGA-GUARD incident desk" },
      {
        name: "description",
        content:
          "Simulation incident desk. Critical faults inhibit the swarm. Human review does not authorize motion.",
      },
    ],
    links: [{ rel: "stylesheet", href: appCss }],
  }),
  shellComponent: RootDocument,
  component: () => (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <PreviewHostBridge />
        <Outlet />
      </AuthProvider>
    </QueryClientProvider>
  ),
  errorComponent: AppErrorComponent,
})

function RootDocument({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  )
}
