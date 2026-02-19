import { useState } from 'react';
import { useApp, type PipelineStage, type MergeSuggestion } from '../context/AppContext';
import { EntityMergeModal } from './EntityMergeModal';

/**
 * Pipeline Controls - Stage buttons for the evidence extraction pipeline
 *
 * Updated to use the unified extraction flow:
 * 1. Extract (snippets + entities + relations in one pass)
 * 2. Generate merge suggestions
 * 3. User confirms/rejects merges
 * 4. Apply merges
 * 5. Continue to mapping/generation
 */
export function PipelineControls() {
  const {
    pipelineState,
    projectId,
    unifiedExtract,
    generateMergeSuggestions,
    confirmMerges,
    applyMerges,
    mergeSuggestions,
    isExtracting,
    isMerging,
    confirmAllMappings,
    generatePetition,
    canExtract,
    canConfirm,
    canGenerate,
    allSnippets,
  } = useApp();

  const { stage, progress, snippetCount, error } = pipelineState;

  // Local state for applicant name input and merge modal
  const [showApplicantInput, setShowApplicantInput] = useState(false);
  const [applicantName, setApplicantName] = useState('');
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [extractionStep, setExtractionStep] = useState<'idle' | 'extracting' | 'suggesting' | 'reviewing' | 'applying'>('idle');

  // Stage display names
  const stageNames: Record<PipelineStage, string> = {
    ocr_complete: 'OCR Complete',
    extracting: 'Extracting...',
    snippets_ready: 'Snippets Ready',
    confirming: 'Confirming...',
    mapping_confirmed: 'Mappings Confirmed',
    generating: 'Generating...',
    petition_ready: 'Petition Ready',
  };

  // Stage colors
  const stageColors: Record<PipelineStage, string> = {
    ocr_complete: 'bg-yellow-100 text-yellow-800 border-yellow-300',
    extracting: 'bg-blue-100 text-blue-800 border-blue-300',
    snippets_ready: 'bg-green-100 text-green-800 border-green-300',
    confirming: 'bg-blue-100 text-blue-800 border-blue-300',
    mapping_confirmed: 'bg-emerald-100 text-emerald-800 border-emerald-300',
    generating: 'bg-blue-100 text-blue-800 border-blue-300',
    petition_ready: 'bg-purple-100 text-purple-800 border-purple-300',
  };

  const isProcessing = stage === 'extracting' || stage === 'confirming' || stage === 'generating' || isExtracting || isMerging;

  // Unified extraction flow
  const handleStartExtraction = () => {
    setShowApplicantInput(true);
  };

  const handleExtract = async () => {
    if (!applicantName.trim()) return;

    setShowApplicantInput(false);
    setExtractionStep('extracting');

    try {
      // Step 1: Run unified extraction
      await unifiedExtract(applicantName);

      // Step 2: Generate merge suggestions
      setExtractionStep('suggesting');
      const suggestions = await generateMergeSuggestions(applicantName);

      // Step 3: Show merge modal if there are suggestions
      if (suggestions.length > 0) {
        setExtractionStep('reviewing');
        setShowMergeModal(true);
      } else {
        setExtractionStep('idle');
      }
    } catch (err) {
      console.error('Extraction failed:', err);
      setExtractionStep('idle');
    }
  };

  const handleMergeConfirm = async (confirmations: Array<{suggestion_id: string; status: string}>) => {
    setShowMergeModal(false);
    setExtractionStep('applying');

    try {
      // Confirm the decisions
      await confirmMerges(confirmations);

      // Apply the accepted merges
      await applyMerges();

      setExtractionStep('idle');
    } catch (err) {
      console.error('Failed to apply merges:', err);
      setExtractionStep('idle');
    }
  };

  const handleMergeClose = () => {
    setShowMergeModal(false);
    setExtractionStep('idle');
  };

  // Get extraction step display text
  const getExtractionStepText = () => {
    switch (extractionStep) {
      case 'extracting': return 'Extracting snippets, entities & relations...';
      case 'suggesting': return 'Generating merge suggestions...';
      case 'reviewing': return 'Review merge suggestions';
      case 'applying': return 'Applying merges...';
      default: return '';
    }
  };

  return (
    <>
      <div className="flex items-center gap-4 px-4 py-2 bg-white border-b border-gray-200">
        {/* Stage Badge */}
        <div className={`px-3 py-1 text-sm font-medium rounded-full border ${stageColors[stage]}`}>
          {stageNames[stage]}
        </div>

        {/* Progress Bar (when processing) */}
        {isProcessing && progress !== undefined && (
          <div className="flex-1 max-w-xs">
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Extraction Step Indicator */}
        {extractionStep !== 'idle' && (
          <div className="flex items-center gap-2 text-sm text-blue-600">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            {getExtractionStepText()}
          </div>
        )}

        {/* Snippet Count */}
        {(stage === 'snippets_ready' || stage === 'mapping_confirmed' || stage === 'petition_ready') && (
          <span className="text-sm text-gray-600">
            {snippetCount || allSnippets.length} snippets
          </span>
        )}

        {/* Action Buttons */}
        <div className="flex-1" />

        {/* Extract Button - shows input dialog first */}
        {canExtract && !showApplicantInput && extractionStep === 'idle' && (
          <button
            onClick={handleStartExtraction}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Extract (Unified)
          </button>
        )}

        {/* Applicant Name Input */}
        {showApplicantInput && (
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={applicantName}
              onChange={(e) => setApplicantName(e.target.value)}
              placeholder="Enter applicant name..."
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleExtract();
                if (e.key === 'Escape') setShowApplicantInput(false);
              }}
            />
            <button
              onClick={handleExtract}
              disabled={!applicantName.trim()}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              Start
            </button>
            <button
              onClick={() => setShowApplicantInput(false)}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
            >
              Cancel
            </button>
          </div>
        )}

        {canConfirm && (
          <button
            onClick={confirmAllMappings}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Confirm Mappings
          </button>
        )}

        {canGenerate && (
          <button
            onClick={generatePetition}
            className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
            Generate Petition
          </button>
        )}

        {stage === 'petition_ready' && (
          <div className="flex items-center gap-2 text-green-600">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="font-medium">Complete</span>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="text-sm text-red-600 flex items-center gap-1">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {error}
          </div>
        )}
      </div>

      {/* Entity Merge Modal */}
      <EntityMergeModal
        isOpen={showMergeModal}
        suggestions={mergeSuggestions}
        onConfirm={handleMergeConfirm}
        onClose={handleMergeClose}
      />
    </>
  );
}

/**
 * Stage Indicator - Shows the current pipeline stage with visual steps
 */
export function PipelineStageIndicator() {
  const { pipelineState } = useApp();
  const { stage } = pipelineState;

  const stages: { key: PipelineStage; label: string; icon: string }[] = [
    { key: 'ocr_complete', label: 'OCR', icon: '1' },
    { key: 'snippets_ready', label: 'Extract', icon: '2' },
    { key: 'mapping_confirmed', label: 'Map', icon: '3' },
    { key: 'petition_ready', label: 'Generate', icon: '4' },
  ];

  const getCurrentStageIndex = () => {
    switch (stage) {
      case 'ocr_complete':
      case 'extracting':
        return 0;
      case 'snippets_ready':
      case 'confirming':
        return 1;
      case 'mapping_confirmed':
      case 'generating':
        return 2;
      case 'petition_ready':
        return 3;
      default:
        return 0;
    }
  };

  const currentIndex = getCurrentStageIndex();

  return (
    <div className="flex items-center gap-2">
      {stages.map((s, index) => {
        const isCompleted = index < currentIndex;
        const isCurrent = index === currentIndex;
        const isProcessing = isCurrent && ['extracting', 'confirming', 'generating'].includes(stage);

        return (
          <div key={s.key} className="flex items-center">
            {/* Step Circle */}
            <div
              className={`
                w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
                transition-all duration-300
                ${isCompleted
                  ? 'bg-green-500 text-white'
                  : isCurrent
                    ? isProcessing
                      ? 'bg-blue-500 text-white animate-pulse'
                      : 'bg-blue-600 text-white'
                    : 'bg-gray-200 text-gray-500'
                }
              `}
            >
              {isCompleted ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                s.icon
              )}
            </div>

            {/* Label */}
            <span
              className={`ml-2 text-sm ${
                isCurrent || isCompleted ? 'text-gray-900 font-medium' : 'text-gray-500'
              }`}
            >
              {s.label}
            </span>

            {/* Connector Line */}
            {index < stages.length - 1 && (
              <div
                className={`
                  mx-3 h-0.5 w-8
                  ${isCompleted ? 'bg-green-500' : 'bg-gray-200'}
                `}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
