/**
 * Snippet Service - Snippet 管理 API
 */

import apiClient from './api';

export interface BBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface SnippetRegistry {
  snippet_id: string;
  document_id: string;
  exhibit_id: string;
  material_id: string;
  text: string;
  page: number;
  bbox: BBox | null;
  standard_key: string;
  source_block_ids: string[];
}

export interface SnippetLink {
  snippet_a: string;
  snippet_b: string;
  link_type: 'co-reference' | 'relation-based' | 'hybrid';
  shared_entities: string[];
  shared_relations?: string[];
  strength: number;
}

export interface SnippetStats {
  total_snippets: number;
  by_standard: Record<string, number>;
  by_exhibit: Record<string, number>;
  with_bbox: number;
  bbox_coverage: number;
}

export const snippetService = {
  /**
   * 获取项目的 snippet 注册表
   */
  getRegistry: (projectId: string) =>
    apiClient.get<{
      success: boolean;
      project_id: string;
      snippets: SnippetRegistry[];
      stats: SnippetStats;
    }>(`/write/v2/${projectId}/snippets`),

  /**
   * 获取某个标准下的所有 snippets
   */
  getByStandard: (projectId: string, standardKey: string) =>
    apiClient.get<{
      success: boolean;
      standard_key: string;
      snippets: SnippetRegistry[];
      count: number;
    }>(`/write/v2/${projectId}/snippets/by-standard/${standardKey}`),

  /**
   * 将 snippet 映射到某个标准
   */
  mapToStandard: (projectId: string, snippetId: string, standardKey: string) =>
    apiClient.post<{
      success: boolean;
      snippet_id: string;
      new_standard_key: string;
    }>(`/write/v2/${projectId}/snippets/map`, {
      snippet_id: snippetId,
      standard_key: standardKey,
    }),

  /**
   * 获取 snippet 关联信息
   */
  getLinks: (projectId: string) =>
    apiClient.get<{
      success: boolean;
      project_id: string;
      links: SnippetLink[];
      link_count: number;
    }>(`/write/v2/${projectId}/links`),

  /**
   * 获取可用的法律标准列表
   */
  getStandards: () =>
    apiClient.get<{
      eb1a: Record<string, string>;
      l1: Record<string, string>;
    }>('/write/v2/standards'),
};

export default snippetService;
