/**
 * Writing Service - 写作生成 API
 */

import apiClient from './api';

export interface AnnotatedSentence {
  text: string;
  snippet_ids: string[];
}

export interface WriteResponse {
  success: boolean;
  section: string;
  paragraph_text: string;
  sentences: AnnotatedSentence[];
  snippet_count: number;
  version_id?: string;
}

export interface SectionWriting {
  version_id: string;
  timestamp: string;
  section: string;
  paragraph_text: string;
  sentences: AnnotatedSentence[];
  sentence_count: number;
  annotated_count: number;
}

export const writingService = {
  /**
   * 生成 petition 段落（两步写作）
   */
  generateSection: (
    projectId: string,
    section: string,
    options?: {
      style_template_id?: string;
      additional_instructions?: string;
    }
  ) =>
    apiClient.post<WriteResponse>(
      `/write/v2/${projectId}/${section}`,
      options || {}
    ),

  /**
   * 获取所有已生成的章节
   */
  getAllSections: (projectId: string) =>
    apiClient.get<{
      success: boolean;
      project_id: string;
      sections: Record<string, SectionWriting>;
      section_count: number;
    }>(`/write/v2/${projectId}/sections`),

  /**
   * 获取单个章节的写作结果
   */
  getSection: (projectId: string, section: string, versionId?: string) => {
    const url = versionId
      ? `/write/v2/${projectId}/section/${section}?version_id=${versionId}`
      : `/write/v2/${projectId}/section/${section}`;
    return apiClient.get<SectionWriting & { success: boolean }>(url);
  },
};

export default writingService;
