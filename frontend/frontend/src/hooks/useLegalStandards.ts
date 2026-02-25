import { useProject } from '../context/ProjectContext';
import { legalStandards as defaultEB1AStandards } from '../data/legalStandards';
import type { LegalStandard } from '../types';

/**
 * Hook to get the legal standards for the current project.
 * Falls back to hardcoded EB-1A standards if none loaded from API.
 */
export function useLegalStandards(): LegalStandard[] {
  const { legalStandards } = useProject();
  return legalStandards.length > 0 ? legalStandards : defaultEB1AStandards;
}
