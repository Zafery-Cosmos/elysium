import { ChatStage, DiffStage, ModelStage, ModesStage, MoreStage, PlanStage, TeamStage } from "./TourStages";
import type { TourStep } from "./TourStages";

/** Ordre des étapes du tutoriel. */
export const TOUR_STEPS: readonly TourStep[] = [
  { id: "team", title: "tour.s0.title", body: "tour.s0.body", Stage: TeamStage },
  { id: "chat", title: "tour.s1.title", body: "tour.s1.body", action: "tour.s1.try", Stage: ChatStage },
  { id: "modes", title: "tour.s2.title", body: "tour.s2.body", action: "tour.s2.try", Stage: ModesStage },
  { id: "plan", title: "tour.s3.title", body: "tour.s3.body", action: "tour.s3.try", Stage: PlanStage },
  { id: "diff", title: "tour.s4.title", body: "tour.s4.body", action: "tour.s4.try", Stage: DiffStage },
  { id: "models", title: "tour.s5.title", body: "tour.s5.body", action: "tour.s5.try", Stage: ModelStage },
  { id: "more", title: "tour.s6.title", body: "tour.s6.body", Stage: MoreStage },
];
