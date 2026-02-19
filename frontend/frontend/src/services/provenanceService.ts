/**
 * Provenance Service - 溯源 API
 */

import apiClient from './api';
import { BBox } from './snippetService';

export interface SnippetMatch {
  snippet_id: string;
  confidence: number;
  match_type: 'explicit' | 'semantic';
  text: string;
  exhibit_id: string;
  page: number;
  bbox: BBox | null;
}

export interface ProvenanceResult {
  sentence_index: number;
  sentence_text: string;
  snippets: SnippetMatch[];
  total_matches: number;
}

export interface SentenceReference {
  section: string;
  sentence_index: number;
  sentence_text: string;
  confidence: number;
  match_type: 'explicit' | 'semantic';
}

export interface ReverseProvenanceResult {
  snippet_id: string;
  snippet_text: string;
  sentences: SentenceReference[];
  total_references: number;
}

export interface BBoxInfo {
  snippet_id: string;
  exhibit_id: string;
  page: number;
  bbox: BBox;
}

export interface ProvenanceSummary {
  section: string;
  sentence_count: number;
  annotated_count: number;
  coverage: number;
  snippet_usage: Record<string, number>;
}

export const provenanceService = {
  /**
   * 正向溯源：获取句子的来源 snippets
   */
  getSentenceProvenance: (
    projectId: string,
    section: string,
    sentenceIndex: number,
    method: 'explicit' | 'semantic' | 'hybrid' = 'hybrid'
  ) =>
    apiClient.get<ProvenanceResult>(
      `/provenance/${projectId}/sentence?section=${encodeURIComponent(section)}&sentence_index=${sentenceIndex}&method=${method}`
    ),

  /**
   * 反向溯源：查找引用了某个 snippet 的所有句子
   */
  getReverseProvenance: (projectId: string, snippetId: string) =>
    apiClient.get<ReverseProvenanceResult>(
      `/provenance/${projectId}/reverse?snippet_id=${encodeURIComponent(snippetId)}`
    ),

  /**
   * 获取多个 snippets 的 BBox 坐标
   */
  getBBox: (projectId: string, snippetIds: string[]) =>
    apiClient.get<{
      success: boolean;
      project_id: string;
      results: BBoxInfo[];
      found: number;
      requested: number;
    }>(`/provenance/${projectId}/bbox?snippet_ids=${snippetIds.join(',')}`),

  /**
   * 获取 section 的溯源统计摘要
   */
  getSummary: (projectId: string, section: string) =>
    apiClient.get<{ success: boolean } & ProvenanceSummary>(
      `/provenance/${projectId}/summary/${section}`
    ),

  /**
   * 获取所有 sections 的溯源统计摘要
   */
  getAllSummaries: (projectId: string) =>
    apiClient.get<{
      success: boolean;
      project_id: string;
      sections: Record<string, ProvenanceSummary>;
      section_count: number;
    }>(`/provenance/${projectId}/all-summaries`),

  /**
   * 获取 section 中所有句子的溯源信息
   */
  getSectionAllSentences: (
    projectId: string,
    section: string,
    method: 'explicit' | 'semantic' | 'hybrid' = 'hybrid'
  ) =>
    apiClient.get<{
      success: boolean;
      section: string;
      sentences: ProvenanceResult[];
      total_sentences: number;
    }>(`/provenance/${projectId}/section/${section}/all-sentences?method=${method}`),
};

export default provenanceService;
