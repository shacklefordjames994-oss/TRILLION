import { createRouter } from "@tanstack/react-router"
import { routeTree } from "./routeTree.gen"
import { previewPathRewrite } from "@/lib/preview-path-prefix"

export const getRouter = () =>
  createRouter({
    routeTree,
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
    rewrite: previewPathRewrite(),
  })
