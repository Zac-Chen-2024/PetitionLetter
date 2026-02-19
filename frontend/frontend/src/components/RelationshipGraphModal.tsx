import { useState, useEffect } from 'react';
import { apiClient } from '../services/api';
import { useApp } from '../context/AppContext';

interface Entity {
  id: string;
  name: string;
  type: string;
  mentions: number;
  snippet_ids: string[];
}

interface Relation {
  from_entity: string;
  to_entity: string;
  relation_type: string;
  snippet_ids: string[];
}

interface Attribution {
  snippet_id: string;
  subject: string;
  achievement_type: string;
  is_applicant: boolean;
  confidence: number;
}

interface RelationshipGraph {
  entities: Entity[];
  relations: Relation[];
  main_subject: string | null;
  attributions?: Attribution[];  // Optional - may not exist in older data
  stats?: {
    total_snippets?: number;
    entity_count?: number;
    relation_count?: number;
    main_subject?: string | null;
    analyzed_at?: string;
  };
  // Extra fields from API
  project_id?: string;
  has_relationship_analysis?: boolean;
}

// Entity type colors
const ENTITY_COLORS: Record<string, string> = {
  person: '#3b82f6',
  organization: '#10b981',
  award: '#f59e0b',
  publication: '#8b5cf6',
  position: '#ec4899',
  project: '#06b6d4',
  event: '#6366f1',
  metric: '#64748b',
};

// Relation type labels
const RELATION_LABELS: Record<string, string> = {
  received: 'Received',
  works_at: 'Works at',
  leads: 'Leads',
  authored: 'Authored',
  founded: 'Founded',
  member_of: 'Member of',
  published_in: 'Published in',
  cited_by: 'Cited by',
  collaborated: 'Collaborated',
  judged: 'Judged',
  owns: 'Owns',
  // Recommendation letter relations
  writes_recommendation_for: 'Recommends',
  recommends_to: 'Recommends to',
  recommends_for_position: 'Recommends for',
  supervised_by: 'Supervised by',
  mentored_by: 'Mentored by',
  trained_by: 'Trained by',
  coached_by: 'Coached by',
  evaluated_by: 'Evaluated by',
};

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export function RelationshipGraphModal({ isOpen, onClose }: Props) {
  const { projectId } = useApp();
  const [graph, setGraph] = useState<RelationshipGraph | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'entities' | 'relations' | 'attributions'>('overview');
  const [selectedEntityType, setSelectedEntityType] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && !graph) {
      loadGraph();
    }
  }, [isOpen]);

  const loadGraph = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<RelationshipGraph>(
        `/arguments/${projectId}/relationship`
      );
      setGraph(response);
    } catch (err) {
      console.error('Failed to load relationship graph:', err);
      setError('No relationship analysis found. Run argument generation first.');
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  // Filter entities by type
  const filteredEntities = graph?.entities.filter(
    e => !selectedEntityType || e.type === selectedEntityType
  ) || [];

  // Get entity type counts
  const entityTypeCounts = graph?.entities.reduce((acc, e) => {
    acc[e.type] = (acc[e.type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>) || {};

  // Get attribution stats (with null safety)
  const applicantSnippets = graph?.attributions?.filter(a => a.is_applicant)?.length || 0;
  const nonApplicantSnippets = graph?.attributions?.filter(a => !a.is_applicant)?.length || 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-[900px] max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Relationship Graph</h2>
            {graph?.main_subject && (
              <p className="text-sm text-slate-500">
                Main Subject: <span className="font-medium text-blue-600">{graph.main_subject}</span>
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {isLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-center">
                <svg className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <p className="text-slate-500">Loading relationship graph...</p>
              </div>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-center">
                <svg className="w-12 h-12 text-slate-300 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-slate-500">{error}</p>
                <button
                  onClick={loadGraph}
                  className="mt-3 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : graph ? (
            <div className="flex flex-col h-full">
              {/* Tabs */}
              <div className="flex gap-1 px-6 py-2 border-b border-slate-200 bg-slate-50">
                {(['overview', 'entities', 'relations', 'attributions'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors capitalize ${
                      activeTab === tab
                        ? 'bg-white text-slate-900 shadow-sm'
                        : 'text-slate-500 hover:text-slate-700 hover:bg-white/50'
                    }`}
                  >
                    {tab}
                  </button>
                ))}
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto p-6">
                {activeTab === 'overview' && (
                  <div className="space-y-6">
                    {/* Stats Grid */}
                    <div className="grid grid-cols-4 gap-4">
                      <div className="bg-blue-50 rounded-lg p-4">
                        <p className="text-2xl font-bold text-blue-600">{graph.entities.length}</p>
                        <p className="text-sm text-blue-600/70">Entities</p>
                      </div>
                      <div className="bg-green-50 rounded-lg p-4">
                        <p className="text-2xl font-bold text-green-600">{graph.relations.length}</p>
                        <p className="text-sm text-green-600/70">Relations</p>
                      </div>
                      <div className="bg-purple-50 rounded-lg p-4">
                        <p className="text-2xl font-bold text-purple-600">{applicantSnippets}</p>
                        <p className="text-sm text-purple-600/70">Applicant Snippets</p>
                      </div>
                      <div className="bg-slate-100 rounded-lg p-4">
                        <p className="text-2xl font-bold text-slate-600">{nonApplicantSnippets}</p>
                        <p className="text-sm text-slate-500">Filtered Out</p>
                      </div>
                    </div>

                    {/* Entity Types */}
                    <div>
                      <h3 className="text-sm font-medium text-slate-700 mb-3">Entity Types</h3>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(entityTypeCounts).map(([type, count]) => (
                          <span
                            key={type}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium"
                            style={{
                              backgroundColor: `${ENTITY_COLORS[type] || '#64748b'}15`,
                              color: ENTITY_COLORS[type] || '#64748b',
                            }}
                          >
                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ENTITY_COLORS[type] || '#64748b' }} />
                            {type}: {count}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Top Entities */}
                    <div>
                      <h3 className="text-sm font-medium text-slate-700 mb-3">Top Mentioned Entities</h3>
                      <div className="space-y-2">
                        {graph.entities
                          .sort((a, b) => b.mentions - a.mentions)
                          .slice(0, 10)
                          .map(entity => (
                            <div
                              key={entity.id}
                              className="flex items-center gap-3 p-2 bg-slate-50 rounded-lg"
                            >
                              <span
                                className="w-2 h-2 rounded-full flex-shrink-0"
                                style={{ backgroundColor: ENTITY_COLORS[entity.type] || '#64748b' }}
                              />
                              <span className="flex-1 text-sm font-medium text-slate-700 truncate">
                                {entity.name}
                              </span>
                              <span className="text-xs text-slate-500 bg-white px-2 py-0.5 rounded">
                                {entity.type}
                              </span>
                              <span className="text-xs font-medium text-slate-600">
                                {entity.mentions}x
                              </span>
                            </div>
                          ))}
                      </div>
                    </div>
                  </div>
                )}

                {activeTab === 'entities' && (
                  <div>
                    {/* Entity Type Filter */}
                    <div className="flex gap-2 mb-4 flex-wrap">
                      <button
                        onClick={() => setSelectedEntityType(null)}
                        className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                          !selectedEntityType
                            ? 'bg-slate-900 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}
                      >
                        All ({graph.entities.length})
                      </button>
                      {Object.entries(entityTypeCounts).map(([type, count]) => (
                        <button
                          key={type}
                          onClick={() => setSelectedEntityType(type)}
                          className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                            selectedEntityType === type
                              ? 'text-white'
                              : 'hover:opacity-80'
                          }`}
                          style={{
                            backgroundColor: selectedEntityType === type
                              ? ENTITY_COLORS[type] || '#64748b'
                              : `${ENTITY_COLORS[type] || '#64748b'}20`,
                            color: selectedEntityType === type
                              ? 'white'
                              : ENTITY_COLORS[type] || '#64748b',
                          }}
                        >
                          {type} ({count})
                        </button>
                      ))}
                    </div>

                    {/* Entity List */}
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {filteredEntities.map(entity => (
                        <div
                          key={entity.id}
                          className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg"
                        >
                          <span
                            className="w-3 h-3 rounded-full flex-shrink-0"
                            style={{ backgroundColor: ENTITY_COLORS[entity.type] || '#64748b' }}
                          />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-slate-700 truncate">
                              {entity.name}
                            </p>
                            <p className="text-xs text-slate-500">
                              {entity.snippet_ids.length} snippets
                            </p>
                          </div>
                          <span className="text-xs text-slate-500 bg-white px-2 py-0.5 rounded">
                            {entity.type}
                          </span>
                          <span className="text-sm font-medium text-slate-600">
                            {entity.mentions}x
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {activeTab === 'relations' && (
                  <div className="space-y-2 max-h-[400px] overflow-y-auto">
                    {graph.relations.map((rel, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 p-3 bg-slate-50 rounded-lg"
                      >
                        <span className="text-sm font-medium text-slate-700 truncate max-w-[200px]">
                          {rel.from_entity}
                        </span>
                        <span className="flex-shrink-0 px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
                          {RELATION_LABELS[rel.relation_type] || rel.relation_type}
                        </span>
                        <svg className="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                        </svg>
                        <span className="text-sm font-medium text-slate-700 truncate max-w-[200px]">
                          {rel.to_entity}
                        </span>
                        <span className="ml-auto text-xs text-slate-400">
                          {rel.snippet_ids.length} refs
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {activeTab === 'attributions' && (
                  <div>
                    {/* Attribution Summary */}
                    <div className="flex gap-4 mb-4">
                      <div className="flex-1 bg-green-50 rounded-lg p-3">
                        <p className="text-lg font-bold text-green-600">{applicantSnippets}</p>
                        <p className="text-xs text-green-600/70">Applicant's Achievements</p>
                      </div>
                      <div className="flex-1 bg-slate-100 rounded-lg p-3">
                        <p className="text-lg font-bold text-slate-500">{nonApplicantSnippets}</p>
                        <p className="text-xs text-slate-500">Others' Achievements (Filtered)</p>
                      </div>
                    </div>

                    {/* Non-applicant attributions */}
                    <h3 className="text-sm font-medium text-slate-700 mb-2">Filtered Out Snippets</h3>
                    <div className="space-y-2 max-h-80 overflow-y-auto">
                      {(graph.attributions || [])
                        .filter(a => !a.is_applicant)
                        .map(attr => (
                          <div
                            key={attr.snippet_id}
                            className="flex items-center gap-3 p-2 bg-slate-50 rounded-lg"
                          >
                            <span className="text-xs text-slate-400 font-mono">
                              {attr.snippet_id.slice(-12)}
                            </span>
                            <span className="flex-1 text-sm text-slate-600">
                              Subject: <span className="font-medium">{attr.subject}</span>
                            </span>
                            <span className="text-xs bg-slate-200 text-slate-600 px-2 py-0.5 rounded">
                              {attr.achievement_type}
                            </span>
                            <span className="text-xs text-slate-400">
                              {Math.round(attr.confidence * 100)}%
                            </span>
                          </div>
                        ))}
                      {nonApplicantSnippets === 0 && (
                        <p className="text-sm text-slate-400 text-center py-4">
                          All snippets belong to the applicant
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        {graph && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-slate-200 bg-slate-50">
            <span className="text-xs text-slate-500">
              {graph.stats?.analyzed_at ? `Analyzed: ${new Date(graph.stats.analyzed_at).toLocaleString()}` : 'Relationship analysis available'}
            </span>
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
