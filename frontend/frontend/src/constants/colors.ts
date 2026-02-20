/**
 * Unified Color System for EB-1A Evidence Mapping
 *
 * Single source of truth for all colors in the application.
 * Colors are based on the 8 EB-1A legal standards.
 */

import type { MaterialType } from '../types';

// EB-1A 10 Legal Standards - Official Colors (8 C.F.R. §204.5(h)(3)(i)-(x))
export const STANDARD_COLORS: Record<string, string> = {
  'std-awards': '#3B82F6',      // blue - (i) Awards
  'std-membership': '#8B5CF6',  // purple - (ii) Membership
  'std-published': '#EC4899',   // pink - (iii) Published Material
  'std-judging': '#F59E0B',     // amber - (iv) Judging
  'std-contribution': '#10B981', // emerald - (v) Original Contribution
  'std-scholarly': '#06B6D4',   // cyan - (vi) Scholarly Articles
  'std-display': '#F472B6',     // pink-400 - (vii) Artistic Display
  'std-leading': '#EF4444',     // red - (viii) Leading/Critical Role
  'std-salary': '#84CC16',      // lime - (ix) High Salary
  'std-commercial': '#A78BFA',  // violet-400 - (x) Commercial Success
} as const;

// MaterialType to Standard ID mapping
export const MATERIAL_TYPE_TO_STANDARD_ID: Record<MaterialType, string> = {
  'award': 'std-awards',
  'membership': 'std-membership',
  'publication': 'std-published',
  'judging': 'std-judging',
  'contribution': 'std-contribution',
  'leadership': 'std-leading',
  'salary': 'std-salary',
  'other': 'std-contribution',
} as const;

// Get color for a materialType (inherits from corresponding standard)
export function getMaterialTypeColor(materialType: MaterialType | string): string {
  const standardId = MATERIAL_TYPE_TO_STANDARD_ID[materialType as MaterialType];
  if (standardId && STANDARD_COLORS[standardId]) {
    return STANDARD_COLORS[standardId];
  }
  return '#64748b'; // slate-500 fallback
}

// Get color for a standard ID
export function getStandardColor(standardId: string): string {
  return STANDARD_COLORS[standardId] || '#64748b';
}

// standardKey (from backend) to standard_id mapping
// Backend uses: awards, membership, scholarly_articles, judging, original_contribution(s), leading_role, high_salary, published_material, display, commercial_success
export const STANDARD_KEY_TO_ID: Record<string, string> = {
  'awards': 'std-awards',
  'membership': 'std-membership',
  'scholarly_articles': 'std-scholarly',
  'judging': 'std-judging',
  'original_contribution': 'std-contribution',
  'original_contributions': 'std-contribution',  // 兼容复数形式
  'display': 'std-display',
  'artistic_display': 'std-display',
  'exhibitions': 'std-display',
  'leading_role': 'std-leading',
  'high_salary': 'std-salary',
  'published_material': 'std-published',
  'commercial_success': 'std-commercial',
  'commercial': 'std-commercial',
} as const;

// Get color for a standardKey (from backend argument)
export function getStandardKeyColor(standardKey: string): string {
  const standardId = STANDARD_KEY_TO_ID[standardKey];
  if (standardId) {
    return STANDARD_COLORS[standardId] || '#64748b';
  }
  return '#64748b'; // slate-500 fallback for unmapped
}

// Material type configuration with colors (for UI components)
export const MATERIAL_TYPE_CONFIG: { value: MaterialType; label: string; color: string }[] = [
  { value: 'award', label: 'Award', color: STANDARD_COLORS['std-awards'] },
  { value: 'membership', label: 'Membership', color: STANDARD_COLORS['std-membership'] },
  { value: 'publication', label: 'Publication', color: STANDARD_COLORS['std-published'] },
  { value: 'judging', label: 'Judging', color: STANDARD_COLORS['std-judging'] },
  { value: 'contribution', label: 'Contribution', color: STANDARD_COLORS['std-contribution'] },
  { value: 'leadership', label: 'Leadership', color: STANDARD_COLORS['std-leading'] },
  { value: 'salary', label: 'Salary', color: STANDARD_COLORS['std-salary'] },
  { value: 'other', label: 'Other', color: '#64748b' },
];
