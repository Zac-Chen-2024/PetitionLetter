import { useState, useRef, useCallback, useEffect } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { useApp } from '../context/AppContext';
import { apiClient } from '../services/api';
import type { Snippet, BoundingBox, MaterialType } from '../types';
import { SnippetCreationModal } from './SnippetCreationModal';

// Configure PDF.js worker - use CDN for compatibility
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

// Backend Exhibit type
interface Exhibit {
  id: string;
  name: string;
  category: string;
  pdf_url: string;
  page_count: number;
}

// Color palette for new snippets
const SNIPPET_COLORS = [
  '#10b981', '#3b82f6', '#8b5cf6', '#f59e0b',
  '#06b6d4', '#ec4899', '#6366f1', '#64748b'
];

// Icon components
const FileIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
  </svg>
);

const ChevronIcon = ({ isOpen }: { isOpen: boolean }) => (
  <svg
    className={`w-4 h-4 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
  >
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
  </svg>
);

const PlusIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
  </svg>
);

const FolderIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
  </svg>
);

// Category colors - simple A, B, C format
const CATEGORY_COLORS: Record<string, string> = {
  'A': '#3b82f6',
  'B': '#10b981',
  'C': '#f59e0b',
  'D': '#8b5cf6',
  'E': '#ec4899',
  'F': '#06b6d4',
  'G': '#6366f1',
  'H': '#64748b',
};

// Extraction state for each category
interface ExtractionState {
  isExtracting: boolean;
  progress: number;
  error?: string;
}

// Extract icon - simple letter E
const ExtractIcon = () => (
  <span className="font-bold text-xs">E</span>
);

// Spinner icon for loading
const SpinnerIcon = () => (
  <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
  </svg>
);

// Snippet bounding box overlay with position tracking
function SnippetBboxOverlay({ snippet, onClick }: { snippet: Snippet; onClick: (e: React.MouseEvent) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const { updatePdfBboxPosition } = useApp();

  // Convert bbox coordinates (assuming 1000x1000 normalized)
  const left = (snippet.boundingBox.x / 1000) * 100;
  const top = (snippet.boundingBox.y / 1000) * 100;
  const width = (snippet.boundingBox.width / 1000) * 100;
  const height = (snippet.boundingBox.height / 1000) * 100;

  // Register position for connection line
  useEffect(() => {
    const updatePosition = () => {
      if (ref.current) {
        const rect = ref.current.getBoundingClientRect();
        // Use right edge center as connection point
        updatePdfBboxPosition(snippet.id, {
          x: rect.right,
          y: rect.top + rect.height / 2,
        });
      }
    };

    updatePosition();
    window.addEventListener('scroll', updatePosition, true);
    window.addEventListener('resize', updatePosition);

    return () => {
      window.removeEventListener('scroll', updatePosition, true);
      window.removeEventListener('resize', updatePosition);
    };
  }, [snippet.id, updatePdfBboxPosition]);

  return (
    <div
      ref={ref}
      onClick={onClick}
      className="absolute transition-all duration-200 border-2 rounded cursor-pointer ring-2 ring-offset-2 ring-blue-500 z-20"
      style={{
        left: `${left}%`,
        top: `${top}%`,
        width: `${width}%`,
        height: `${height}%`,
        backgroundColor: `${snippet.color}30`,
        borderColor: snippet.color,
      }}
      title={snippet.summary}
    >
      {/* Snippet indicator badge */}
      <div
        className="absolute -top-2 -right-2 w-5 h-5 rounded-full flex items-center justify-center text-white text-xs font-medium shadow-sm"
        style={{ backgroundColor: snippet.color }}
      >
        {snippet.id.slice(-3)}
      </div>
    </div>
  );
}

interface PDFViewerProps {
  pdfUrl: string;
  pageCount: number;
  exhibitId: string;
  snippets: Snippet[];
  isSelectMode: boolean;
  onSelectionComplete: (boundingBox: BoundingBox, documentId: string) => void;
}

function PDFViewer({
  pdfUrl,
  pageCount,
  exhibitId,
  snippets,
  isSelectMode,
  onSelectionComplete,
}: PDFViewerProps) {
  // Use selectedSnippetId for PDF highlight (not focusState which is for filtering)
  const { selectedSnippetId, setSelectedSnippetId, setSelectedDocumentId } = useApp();
  const containerRef = useRef<HTMLDivElement>(null);
  const [numPages, setNumPages] = useState<number>(0);
  const [scale, setScale] = useState(1);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [containerWidth, setContainerWidth] = useState<number>(0);

  // Number of pages to render at once for continuous scrolling
  const PAGES_TO_RENDER = 10;

  // Track container width for responsive PDF sizing using ResizeObserver
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateWidth = () => {
      // Use full container width for PDF to fill the space
      setContainerWidth(container.clientWidth);
    };

    // Initial measurement
    updateWidth();

    // Use ResizeObserver for container-specific resize detection
    const resizeObserver = new ResizeObserver(() => {
      updateWidth();
    });
    resizeObserver.observe(container);

    // Also listen to window resize as fallback
    window.addEventListener('resize', updateWidth);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', updateWidth);
    };
  }, []);

  // Auto-scroll to snippet's page when selectedSnippetId changes
  useEffect(() => {
    if (selectedSnippetId) {
      const snippet = snippets.find(s => s.id === selectedSnippetId);
      if (snippet && snippet.boundingBox?.page && containerRef.current) {
        const targetPage = snippet.boundingBox.page;
        // Find page elements by data attribute
        const pageElement = containerRef.current.querySelector(`[data-page="${targetPage}"]`);
        if (pageElement) {
          pageElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }
  }, [selectedSnippetId, snippets]);

  // Filter snippets for this exhibit
  const exhibitSnippets = snippets.filter(s => s.exhibitId === exhibitId);

  const handleSnippetClick = (e: React.MouseEvent, snippet: Snippet) => {
    if (isSelectMode) return;
    e.stopPropagation();
    // Clicking snippet in PDF viewer toggles selectedSnippetId (for highlight)
    if (selectedSnippetId === snippet.id) {
      setSelectedSnippetId(null);
    } else {
      setSelectedSnippetId(snippet.id);
      setSelectedDocumentId(snippet.documentId);
    }
  };

  // Get backend URL
  const backendUrl = 'http://localhost:8000';
  const fullPdfUrl = `${backendUrl}${pdfUrl}`;

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setIsLoading(false);
    setPdfError(null);
  };

  const onDocumentLoadError = (error: Error) => {
    console.error('PDF load error:', error);
    setPdfError('Failed to load PDF');
    setIsLoading(false);
  };

  // Calculate how many pages to actually render
  const pagesToRender = Math.min(numPages || pageCount, PAGES_TO_RENDER);
  // Use container width for responsive sizing, fallback to 550 if not measured yet
  const baseWidth = containerWidth > 0 ? containerWidth : 550;
  const pageWidth = baseWidth * scale;

  return (
    <div className="flex flex-col h-full">
      {/* PDF Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-100 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600">
            {numPages > 0 ? `${numPages} pages` : 'Loading...'}
          </span>
          {numPages > PAGES_TO_RENDER && (
            <span className="text-xs text-slate-400">
              (showing first {PAGES_TO_RENDER})
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setScale(s => Math.max(0.5, s - 0.25))}
            className="px-2 py-1 text-sm bg-white border rounded hover:bg-slate-50"
          >
            -
          </button>
          <span className="text-sm text-slate-600">{Math.round(scale * 100)}%</span>
          <button
            onClick={() => setScale(s => Math.min(2, s + 0.25))}
            className="px-2 py-1 text-sm bg-white border rounded hover:bg-slate-50"
          >
            +
          </button>
        </div>
      </div>

      {/* PDF Content with Continuous Scrolling */}
      <div
        ref={containerRef}
        className="flex-1 overflow-auto bg-slate-300"
      >
        {pdfError ? (
          <div className="h-full flex items-center justify-center text-red-500">
            {pdfError}
          </div>
        ) : (
          <Document
            file={fullPdfUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={
              <div className="flex items-center justify-center py-8">
                <div className="text-slate-500">Loading PDF...</div>
              </div>
            }
            className="flex flex-col items-center"
          >
            {Array.from({ length: pagesToRender }, (_, index) => {
              const pageNumber = index + 1;
              const pageSnippets = exhibitSnippets.filter(
                s => s.page === pageNumber || s.boundingBox.page === pageNumber
              );

              return (
                <div
                  key={`page_${pageNumber}`}
                  data-page={pageNumber}
                  className="relative bg-white"
                  style={{
                    width: `${pageWidth}px`,
                    marginBottom: index < pagesToRender - 1 ? '2px' : '0',
                  }}
                >
                  {/* Page number indicator - subtle overlay */}
                  <div className="absolute top-2 right-2 text-xs text-slate-400 bg-white/80 px-1.5 py-0.5 rounded z-10">
                    {pageNumber}
                  </div>

                  <Page
                    pageNumber={pageNumber}
                    width={pageWidth}
                    renderTextLayer={false}
                    renderAnnotationLayer={false}
                    loading={
                      <div
                        className="flex items-center justify-center bg-slate-100"
                        style={{ width: `${pageWidth}px`, height: `${pageWidth * 1.3}px` }}
                      >
                        <span className="text-slate-400">Loading page {pageNumber}...</span>
                      </div>
                    }
                  />

                  {/* Snippet Overlays for this page - only show when snippet is selected from Evidence Cards */}
                  {selectedSnippetId && pageSnippets.map((snippet) => {
                    const isSelected = selectedSnippetId === snippet.id;
                    if (!isSelected) return null;
                    return (
                      <SnippetBboxOverlay
                        key={snippet.id}
                        snippet={snippet}
                        onClick={(e) => handleSnippetClick(e, snippet)}
                      />
                    );
                  })}
                </div>
              );
            })}
          </Document>
        )}
      </div>
    </div>
  );
}

export function DocumentViewer() {
  const { projectId, selectedDocumentId, setSelectedDocumentId, addSnippet, allSnippets, reloadSnippets } = useApp();
  const [exhibits, setExhibits] = useState<Exhibit[]>([]);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['A', 'B']));
  const [isLoading, setIsLoading] = useState(true);
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [pendingSelection, setPendingSelection] = useState<{
    boundingBox: BoundingBox;
    documentId: string;
  } | null>(null);

  // Extraction state management
  const [extractionStates, setExtractionStates] = useState<Record<string, ExtractionState>>({});
  const [isExtractingAll, setIsExtractingAll] = useState(false);
  const [extractAllProgress, setExtractAllProgress] = useState(0);

  // Extract snippets for a specific category
  const handleExtractCategory = async (category: string, exhibitIds: string[]) => {
    setExtractionStates(prev => ({
      ...prev,
      [category]: { isExtracting: true, progress: 0 }
    }));

    try {
      let completed = 0;
      for (const exhibitId of exhibitIds) {
        await apiClient.post(`/analysis/extract/${projectId}/${exhibitId}`, { use_llm: true });
        completed++;
        setExtractionStates(prev => ({
          ...prev,
          [category]: { isExtracting: true, progress: Math.round((completed / exhibitIds.length) * 100) }
        }));
      }

      setExtractionStates(prev => ({
        ...prev,
        [category]: { isExtracting: false, progress: 100 }
      }));

      // Reload snippets after extraction
      await reloadSnippets();
    } catch (error) {
      console.error('Extraction failed:', error);
      setExtractionStates(prev => ({
        ...prev,
        [category]: { isExtracting: false, progress: 0, error: 'Extraction failed' }
      }));
    }
  };

  // Extract all snippets
  const handleExtractAll = async () => {
    setIsExtractingAll(true);
    setExtractAllProgress(0);

    try {
      const result = await apiClient.post<{
        success: boolean;
        snippet_count: number;
        message: string;
      }>(`/analysis/extract/${projectId}`, { use_llm: true });

      if (result.success) {
        setExtractAllProgress(100);
        // Reload snippets after extraction
        await reloadSnippets();
      }
    } catch (error) {
      console.error('Extract all failed:', error);
    } finally {
      setIsExtractingAll(false);
    }
  };

  // Fetch exhibits from backend
  useEffect(() => {
    async function loadExhibits() {
      setIsLoading(true);
      try {
        const response = await apiClient.get<{
          project_id: string;
          total: number;
          exhibits: Exhibit[];
        }>(`/documents/${projectId}/exhibits`);

        if (response.exhibits) {
          setExhibits(response.exhibits);
          // Auto-select first exhibit if none selected
          if (!selectedDocumentId && response.exhibits.length > 0) {
            setSelectedDocumentId(`doc_${response.exhibits[0].id}`);
          }
        }
      } catch (err) {
        console.error('Failed to load exhibits:', err);
      } finally {
        setIsLoading(false);
      }
    }

    loadExhibits();
  }, [projectId]);

  // Group exhibits by category
  const exhibitsByCategory = exhibits.reduce((acc, exhibit) => {
    const category = exhibit.category;
    if (!acc[category]) {
      acc[category] = [];
    }
    acc[category].push(exhibit);
    return acc;
  }, {} as Record<string, Exhibit[]>);

  const toggleCategory = (category: string) => {
    setExpandedCategories(prev => {
      const newSet = new Set(prev);
      if (newSet.has(category)) {
        newSet.delete(category);
      } else {
        newSet.add(category);
      }
      return newSet;
    });
  };

  const handleExhibitClick = (exhibit: Exhibit) => {
    setSelectedDocumentId(`doc_${exhibit.id}`);
  };

  const handleSelectionComplete = useCallback((boundingBox: BoundingBox, documentId: string) => {
    setPendingSelection({ boundingBox, documentId });
    setIsSelectMode(false);
  }, []);

  const handleCreateSnippet = useCallback((data: {
    content: string;
    summary: string;
    materialType: MaterialType;
  }) => {
    if (!pendingSelection) return;

    const colorIndex = {
      salary: 0, leadership: 1, contribution: 2, award: 3,
      membership: 4, publication: 5, judging: 6, other: 7,
    }[data.materialType] || 7;

    addSnippet({
      documentId: pendingSelection.documentId,
      content: data.content,
      summary: data.summary,
      boundingBox: pendingSelection.boundingBox,
      materialType: data.materialType,
      color: SNIPPET_COLORS[colorIndex],
    });

    setPendingSelection(null);
  }, [pendingSelection, addSnippet]);

  // Get selected exhibit
  const selectedExhibitId = selectedDocumentId?.replace('doc_', '');
  const selectedExhibit = exhibits.find(e => e.id === selectedExhibitId);
  const selectedSnippets = allSnippets.filter(s => s.exhibitId === selectedExhibitId);

  return (
    <div className="flex flex-col h-full bg-slate-50">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Document Viewer</h2>
          <button
            onClick={() => setIsSelectMode(!isSelectMode)}
            className={`
              flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors
              ${isSelectMode
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'text-slate-600 bg-slate-100 hover:bg-slate-200'
              }
            `}
          >
            {isSelectMode ? (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
                <span>Cancel</span>
              </>
            ) : (
              <>
                <PlusIcon />
                <span>New Snippet</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Exhibit List */}
      <div className="flex-shrink-0 border-b border-slate-200 bg-white max-h-48 overflow-y-auto">
        <div className="px-3 py-2">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Exhibits ({exhibits.length})
            </div>
            <button
              onClick={handleExtractAll}
              disabled={isExtractingAll || exhibits.length === 0}
              className={`
                flex items-center gap-1 px-2 py-1 text-xs font-medium rounded transition-colors
                ${isExtractingAll
                  ? 'bg-blue-100 text-blue-600 cursor-not-allowed'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
                }
              `}
              title="Extract snippets from all exhibits"
            >
              {isExtractingAll ? (
                <>
                  <SpinnerIcon />
                  <span>Extracting...</span>
                </>
              ) : (
                <>
                  <ExtractIcon />
                  <span>Extract All</span>
                </>
              )}
            </button>
          </div>

          {isLoading ? (
            <div className="text-sm text-slate-500 py-2">Loading exhibits...</div>
          ) : (
            <div className="space-y-1">
              {Object.entries(exhibitsByCategory).map(([category, categoryExhibits]) => {
                const isExpanded = expandedCategories.has(category);
                const categoryColor = CATEGORY_COLORS[category] || '#64748b';
                const extractState = extractionStates[category];
                const isExtracting = extractState?.isExtracting || false;

                return (
                  <div key={category}>
                    {/* Category Header */}
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => toggleCategory(category)}
                        className="flex-1 flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-100 text-left"
                      >
                        <ChevronIcon isOpen={isExpanded} />
                        <FolderIcon />
                        <span className="flex-1 text-sm font-medium text-slate-700">
                          Exhibit {category}
                        </span>
                        <span className="text-xs text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                          {categoryExhibits.length}
                        </span>
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleExtractCategory(category, categoryExhibits.map(e => e.id));
                        }}
                        disabled={isExtracting || isExtractingAll}
                        className={`
                          flex items-center gap-1 px-1.5 py-1 text-xs rounded transition-colors
                          ${isExtracting
                            ? 'bg-slate-100 text-slate-500 cursor-not-allowed'
                            : 'text-slate-500 hover:bg-slate-200 hover:text-slate-700'
                          }
                        `}
                        title={`Extract snippets from Exhibit ${category}`}
                      >
                        {isExtracting ? (
                          <>
                            <SpinnerIcon />
                            <span>{extractState?.progress || 0}%</span>
                          </>
                        ) : (
                          <ExtractIcon />
                        )}
                      </button>
                    </div>

                    {/* Category Exhibits */}
                    {isExpanded && (
                      <div className="ml-6 space-y-0.5">
                        {categoryExhibits.map((exhibit) => {
                          const isSelected = `doc_${exhibit.id}` === selectedDocumentId;
                          const exhibitSnippets = allSnippets.filter(s => s.exhibitId === exhibit.id);

                          return (
                            <button
                              key={exhibit.id}
                              onClick={() => handleExhibitClick(exhibit)}
                              className={`
                                w-full flex items-center gap-2 px-2 py-1 rounded text-left text-sm transition-colors
                                ${isSelected
                                  ? 'bg-slate-900 text-white'
                                  : 'text-slate-600 hover:bg-slate-100'
                                }
                              `}
                            >
                              <FileIcon />
                              <span className="flex-1 truncate">{exhibit.name}</span>
                              <span className={`
                                text-xs px-1.5 py-0.5 rounded
                                ${isSelected ? 'bg-white/20' : 'bg-slate-100'}
                              `}>
                                {exhibit.page_count}p
                              </span>
                              {/* 已提取完成的勾号 */}
                              {exhibitSnippets.length > 0 ? (
                                <svg
                                  className={`w-4 h-4 ${isSelected ? 'text-green-300' : 'text-green-500'}`}
                                  fill="none"
                                  stroke="currentColor"
                                  viewBox="0 0 24 24"
                                >
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                              ) : (
                                <span className={`w-4 h-4 text-xs ${isSelected ? 'text-slate-400' : 'text-slate-300'}`}>
                                  —
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* PDF Viewer */}
      <div className="flex-1 overflow-hidden">
        {selectedExhibit ? (
          <PDFViewer
            pdfUrl={selectedExhibit.pdf_url}
            pageCount={selectedExhibit.page_count}
            exhibitId={selectedExhibit.id}
            snippets={selectedSnippets}
            isSelectMode={isSelectMode}
            onSelectionComplete={handleSelectionComplete}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-slate-500">
            {isLoading ? 'Loading...' : 'Select an exhibit to view'}
          </div>
        )}
      </div>

      {/* Snippet Creation Modal */}
      {pendingSelection && (
        <SnippetCreationModal
          boundingBox={pendingSelection.boundingBox}
          documentId={pendingSelection.documentId}
          onConfirm={handleCreateSnippet}
          onCancel={() => setPendingSelection(null)}
        />
      )}
    </div>
  );
}
