/**
 * EB-1A Legal Standards Configuration
 *
 * This file contains ONLY real configuration data used in production.
 * No mock data - all business data comes from the backend API.
 */

import type { LegalStandard } from '../types';
import { STANDARD_COLORS } from '../constants/colors';

// EB-1A 10 Legal Standards (8 C.F.R. §204.5(h)(3)(i)-(x))
export const legalStandards: LegalStandard[] = [
  {
    id: 'std-awards',
    name: 'Awards',
    shortName: 'Awards',
    description: '(i) Nationally or internationally recognized prizes or awards for excellence',
    color: STANDARD_COLORS['std-awards'],
    order: 1,
  },
  {
    id: 'std-membership',
    name: 'Membership',
    shortName: 'Membership',
    description: '(ii) Membership in associations requiring outstanding achievements',
    color: STANDARD_COLORS['std-membership'],
    order: 2,
  },
  {
    id: 'std-published',
    name: 'Published Material',
    shortName: 'Published',
    description: '(iii) Published material about the alien in professional publications',
    color: STANDARD_COLORS['std-published'],
    order: 3,
  },
  {
    id: 'std-judging',
    name: 'Judging',
    shortName: 'Judging',
    description: '(iv) Participation as a judge of the work of others',
    color: STANDARD_COLORS['std-judging'],
    order: 4,
  },
  {
    id: 'std-contribution',
    name: 'Original Contribution',
    shortName: 'Contribution',
    description: '(v) Original scientific, scholarly, or business contributions of major significance',
    color: STANDARD_COLORS['std-contribution'],
    order: 5,
  },
  {
    id: 'std-scholarly',
    name: 'Scholarly Articles',
    shortName: 'Scholarly',
    description: '(vi) Authorship of scholarly articles in professional journals',
    color: STANDARD_COLORS['std-scholarly'],
    order: 6,
  },
  {
    id: 'std-display',
    name: 'Artistic Display',
    shortName: 'Display',
    description: '(vii) Display of work at artistic exhibitions or showcases',
    color: STANDARD_COLORS['std-display'] || '#F472B6',  // pink-400
    order: 7,
  },
  {
    id: 'std-leading',
    name: 'Leading/Critical Role',
    shortName: 'Leading Role',
    description: '(viii) Leading or critical role in distinguished organizations',
    color: STANDARD_COLORS['std-leading'],
    order: 8,
  },
  {
    id: 'std-salary',
    name: 'High Salary',
    shortName: 'High Salary',
    description: '(ix) High salary or remuneration significantly above others in the field',
    color: STANDARD_COLORS['std-salary'],
    order: 9,
  },
  {
    id: 'std-commercial',
    name: 'Commercial Success',
    shortName: 'Commercial',
    description: '(x) Commercial success in the performing arts (box office, sales, etc.)',
    color: STANDARD_COLORS['std-commercial'] || '#A78BFA',  // violet-400
    order: 10,
  },
];

// Helper to get standard by ID
export const getStandardById = (id: string): LegalStandard | undefined => {
  return legalStandards.find(std => std.id === id);
};

// Material type labels for display
export const materialTypeLabels: Record<string, string> = {
  salary: 'Salary',
  leadership: 'Leadership',
  contribution: 'Contribution',
  award: 'Award',
  membership: 'Membership',
  publication: 'Publication',
  judging: 'Judging',
  other: 'Other',
};

// Quality status configuration
export const qualityStatusConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  pending: { label: '待审核', color: '#6B7280', bgColor: '#F3F4F6' },
  approved: { label: '已批准', color: '#059669', bgColor: '#D1FAE5' },
  rejected: { label: '已拒绝', color: '#DC2626', bgColor: '#FEE2E2' },
  needs_review: { label: '需修改', color: '#D97706', bgColor: '#FEF3C7' },
};
