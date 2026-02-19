/**
 * Project Service - 项目管理 API
 */

import apiClient from './api';

export interface Project {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  beneficiary_name?: string;
  visa_type?: 'eb1a' | 'l1';
}

export interface Document {
  id: string;
  project_id: string;
  file_name: string;
  file_type: string;
  page_count: number;
  ocr_status: string;
  exhibit_id?: string;
}

export const projectService = {
  /**
   * 获取所有项目列表
   */
  list: () => apiClient.get<Project[]>('/projects'),

  /**
   * 创建新项目
   */
  create: (name: string) =>
    apiClient.post<Project>('/projects', { name }),

  /**
   * 获取项目详情
   */
  get: (projectId: string) =>
    apiClient.get<Project>(`/projects/${projectId}`),

  /**
   * 更新项目元数据
   */
  update: (projectId: string, updates: Partial<Project>) =>
    apiClient.patch<Project>(`/projects/${projectId}`, updates),

  /**
   * 删除项目
   */
  delete: (projectId: string) =>
    apiClient.delete<{ success: boolean }>(`/projects/${projectId}`),

  /**
   * 获取项目的所有文档
   */
  getDocuments: (projectId: string) =>
    apiClient.get<Document[]>(`/projects/${projectId}/documents`),

  /**
   * 获取分析结果
   */
  getAnalysis: (projectId: string) =>
    apiClient.get<{ version_id: string; results: unknown }>(`/projects/${projectId}/analysis`),

  /**
   * 获取关系分析结果
   */
  getRelationship: (projectId: string) =>
    apiClient.get<{
      version_id: string;
      data: {
        entities: Array<{
          id: string;
          name: string;
          type: string;
          quote_refs: number[];
        }>;
        relations: Array<{
          from_entity: string;
          to_entity: string;
          relation_type: string;
          quote_refs: number[];
        }>;
      };
    }>(`/projects/${projectId}/relationship`),
};

export default projectService;
