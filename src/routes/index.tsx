import { createFileRoute } from "@tanstack/react-router"
import { IncidentDeskView } from "@/components/incident-desk"

export const Route = createFileRoute("/")({
  component: IncidentDeskView,
})
