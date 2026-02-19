/**
 * Services - 导出所有 API 服务
 */

export { default as apiClient, ApiError } from './api';
export { default as projectService } from './projectService';
export { default as snippetService } from './snippetService';
export { default as writingService } from './writingService';
export { default as provenanceService } from './provenanceService';
export { interactionLogger, logInteraction } from './interactionLogger';

// 类型导出
export type { Project, Document } from './projectService';
export type { SnippetRegistry, SnippetLink, SnippetStats, BBox } from './snippetService';
export type { AnnotatedSentence, WriteResponse, SectionWriting } from './writingService';
export type {
  SnippetMatch,
  ProvenanceResult,
  SentenceReference,
  ReverseProvenanceResult,
  BBoxInfo,
  ProvenanceSummary,
} from './provenanceService';
export type { InteractionLog, EventType } from './interactionLogger';
