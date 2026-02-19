/**
 * Interaction Logger - 交互日志记录服务
 *
 * 用于记录用户在 Condition A 系统中的交互行为
 * 支持 User Study 的行为分析
 */

export type EventType =
  | 'snippet_drag'       // 拖拽 snippet 到 standard
  | 'mapping_confirm'    // 确认 AI 映射（dashed → solid）
  | 'mapping_reject'     // 拒绝 AI 映射
  | 'mapping_create'     // 手动创建新映射
  | 'sentence_click'     // 点击句子查看溯源
  | 'provenance_correct' // 纠正溯源结果
  | 'error_mark'         // 标记错误
  | 'bundle_create'      // 创建 evidence bundle
  | 'bundle_modify'      // 修改 bundle
  | 'document_view'      // 查看文档页面
  | 'bbox_highlight';    // 高亮 bbox

export interface InteractionLog {
  timestamp: number;
  event_type: EventType;
  data: {
    snippet_id?: string;
    standard_key?: string;
    sentence_index?: number;
    section?: string;
    page?: number;
    exhibit_id?: string;
    error_type?: string;
    selection?: string;
    [key: string]: unknown;
  };
}

const STORAGE_KEY = 'interaction_logs';
const BATCH_SIZE = 50;

class InteractionLoggerService {
  private logs: InteractionLog[] = [];
  private sessionId: string;
  private projectId: string | null = null;

  constructor() {
    this.sessionId = this.generateSessionId();
    this.loadFromStorage();
  }

  private generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  private loadFromStorage(): void {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        this.logs = JSON.parse(stored);
      }
    } catch (e) {
      console.error('Failed to load interaction logs:', e);
      this.logs = [];
    }
  }

  private saveToStorage(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.logs));
    } catch (e) {
      console.error('Failed to save interaction logs:', e);
    }
  }

  /**
   * 设置当前项目 ID
   */
  setProjectId(projectId: string): void {
    this.projectId = projectId;
  }

  /**
   * 记录交互事件
   */
  log(eventType: EventType, data: InteractionLog['data'] = {}): void {
    const log: InteractionLog = {
      timestamp: Date.now(),
      event_type: eventType,
      data: {
        ...data,
        session_id: this.sessionId,
        project_id: this.projectId,
      },
    };

    this.logs.push(log);
    this.saveToStorage();

    // 达到批次大小时自动上传
    if (this.logs.length >= BATCH_SIZE) {
      this.flush();
    }
  }

  /**
   * 批量上传日志到后端
   */
  async flush(): Promise<void> {
    if (this.logs.length === 0) return;

    const logsToUpload = [...this.logs];

    try {
      // TODO: 实现后端上传接口
      // await apiClient.post('/logs/interactions', {
      //   session_id: this.sessionId,
      //   project_id: this.projectId,
      //   logs: logsToUpload,
      // });

      // 上传成功后清空
      this.logs = [];
      this.saveToStorage();

      console.log(`[Logger] Flushed ${logsToUpload.length} logs`);
    } catch (e) {
      console.error('Failed to flush logs:', e);
      // 保留日志，下次重试
    }
  }

  /**
   * 获取当前会话的所有日志
   */
  getLogs(): InteractionLog[] {
    return [...this.logs];
  }

  /**
   * 导出日志为 JSON
   */
  exportAsJson(): string {
    return JSON.stringify({
      session_id: this.sessionId,
      project_id: this.projectId,
      exported_at: new Date().toISOString(),
      logs: this.logs,
    }, null, 2);
  }

  /**
   * 清空所有日志
   */
  clear(): void {
    this.logs = [];
    localStorage.removeItem(STORAGE_KEY);
  }

  /**
   * 获取统计信息
   */
  getStats(): Record<EventType, number> {
    const stats: Partial<Record<EventType, number>> = {};

    for (const log of this.logs) {
      stats[log.event_type] = (stats[log.event_type] || 0) + 1;
    }

    return stats as Record<EventType, number>;
  }
}

// 单例导出
export const interactionLogger = new InteractionLoggerService();

// 便捷函数
export const logInteraction = (eventType: EventType, data?: InteractionLog['data']) =>
  interactionLogger.log(eventType, data);

export default interactionLogger;
