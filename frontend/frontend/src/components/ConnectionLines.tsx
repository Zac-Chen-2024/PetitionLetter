import { useEffect, useState, useCallback } from 'react';
import { useApp } from '../context/AppContext';
import { getStandardKeyColor } from '../constants/colors';

// Panel boundary calculation based on new layout percentages
// Layout: DocumentViewer (25%) | EvidenceCards (40%) | ArgumentAssembly (35%)
function usePanelBounds() {
  const [bounds, setBounds] = useState({
    evidenceCards: { left: 0, top: 0, right: 0, bottom: 0 },
    argumentAssembly: { left: 0, top: 0, right: 0, bottom: 0 },
  });

  const updateBounds = useCallback(() => {
    const width = window.innerWidth;
    const height = window.innerHeight;

    // Find the header height (assuming ~100px for header + view mode switcher)
    const headerHeight = 100;

    // Panel widths as percentages
    const docViewerWidth = width * 0.25;
    const evidenceCardsWidth = width * 0.40;
    const argumentWidth = width * 0.35;

    setBounds({
      evidenceCards: {
        left: docViewerWidth,
        top: headerHeight,
        right: docViewerWidth + evidenceCardsWidth,
        bottom: height,
      },
      argumentAssembly: {
        left: docViewerWidth + evidenceCardsWidth,
        top: headerHeight,
        right: docViewerWidth + evidenceCardsWidth + argumentWidth,
        bottom: height,
      },
    });
  }, []);

  useEffect(() => {
    updateBounds();
    window.addEventListener('resize', updateBounds);
    return () => window.removeEventListener('resize', updateBounds);
  }, [updateBounds]);

  return bounds;
}

// Simple curved line helper
function CurvedLine({
  startX, startY, endX, endY, color, strokeWidth = 2.5, glow = false
}: {
  startX: number; startY: number; endX: number; endY: number;
  color: string; strokeWidth?: number; glow?: boolean;
}) {
  const controlOffset = Math.min(60, Math.abs(endX - startX) * 0.35);
  const pathD = `M ${startX} ${startY} C ${startX + controlOffset} ${startY}, ${endX - controlOffset} ${endY}, ${endX} ${endY}`;

  return (
    <g className="transition-all duration-300">
      {glow && (
        <path d={pathD} fill="none" stroke={color} strokeWidth={strokeWidth + 5} strokeOpacity={0.15} strokeLinecap="round" />
      )}
      <path d={pathD} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
      <circle cx={startX} cy={startY} r={4} fill="white" />
      <circle cx={startX} cy={startY} r={2.5} fill={color} />
      <circle cx={endX} cy={endY} r={4} fill="white" />
      <circle cx={endX} cy={endY} r={2.5} fill={color} />
    </g>
  );
}

// Connection lines for a focused snippet (PDF → Card → SubArgument)
function SnippetConnectionLines({ snippetId }: { snippetId: string }) {
  const {
    snippetPositions, pdfBboxPositions, allSnippets,
    subArguments, subArgumentPositions
  } = useApp();

  const snippet = allSnippets.find(s => s.id === snippetId);
  const cardPos = snippetPositions.get(snippetId);
  const bboxPos = pdfBboxPositions.get(snippetId);

  if (!snippet) return null;

  const color = snippet.color || '#3b82f6';

  // Calculate card left edge (cardPos.x is right edge)
  const cardLeftX = cardPos ? cardPos.x - (cardPos.width || 0) : 0;
  const cardRightX = cardPos?.x || 0;
  const cardY = cardPos?.y || 0;

  // Find sub-arguments that contain this snippet
  const relatedSubArguments = subArguments.filter(sa => sa.snippetIds?.includes(snippetId));

  return (
    <g>
      {/* 1. PDF bounding box → Evidence Card LEFT side */}
      {cardPos && bboxPos && (
        <CurvedLine
          startX={bboxPos.x}
          startY={bboxPos.y}
          endX={cardLeftX}
          endY={cardY}
          color={color}
          glow={true}
        />
      )}

      {/* 2. Evidence Card RIGHT side → SubArgument(s) LEFT side */}
      {cardPos && relatedSubArguments.map(subArg => {
        const subArgPos = subArgumentPositions.get(subArg.id);
        if (!subArgPos) return null;
        return (
          <CurvedLine
            key={`snippet-subarg-${subArg.id}`}
            startX={cardRightX}
            startY={cardY}
            endX={subArgPos.x - (subArgPos.width || 0)} // Connect to LEFT side of sub-argument
            endY={subArgPos.y}
            color={color}
            strokeWidth={2}
          />
        );
      })}
    </g>
  );
}

// Connection lines for a focused SubArgument (show Snippet → SubArgument connections)
function SubArgumentConnectionLines({ subArgumentId }: { subArgumentId: string }) {
  const {
    allSnippets, snippetPositions,
    arguments: arguments_, subArguments, subArgumentPositions
  } = useApp();

  const subArgument = subArguments.find(sa => sa.id === subArgumentId);
  if (!subArgument) return null;

  const subArgPos = subArgumentPositions.get(subArgumentId);
  if (!subArgPos) return null;

  // Find parent argument to get the color
  const parentArgument = arguments_.find(a => a.id === subArgument.argumentId);
  const standardColor = parentArgument?.standardKey
    ? getStandardKeyColor(parentArgument.standardKey)
    : '#10b981'; // emerald color for sub-arguments

  const subArgLeftX = subArgPos.x - (subArgPos.width || 0);

  return (
    <g>
      {/* Draw connections from snippets to this sub-argument */}
      {(subArgument.snippetIds || []).map(snippetId => {
        const snippet = allSnippets.find(s => s.id === snippetId);
        const cardPos = snippetPositions.get(snippetId);
        if (!snippet || !cardPos) return null;

        return (
          <CurvedLine
            key={`subarg-snip-${snippetId}`}
            startX={cardPos.x} // Right side of snippet card
            startY={cardPos.y}
            endX={subArgLeftX} // Left side of sub-argument
            endY={subArgPos.y}
            color={standardColor}
            strokeWidth={2.5}
            glow={true}
          />
        );
      })}
    </g>
  );
}

// Connection lines for a focused Standard - disabled to reduce visual clutter
// Only highlight argument cards, no connection lines to sub-arguments
function StandardConnectionLines({ standardId }: { standardId: string }) {
  // Return empty - no connection lines when standard is focused
  // Arguments are highlighted via ArgumentGraph component
  return null;
}

export function ConnectionLines() {
  const { focusState, selectedSnippetId } = useApp();
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const panelBounds = usePanelBounds();

  useEffect(() => {
    const updateDimensions = () => {
      setDimensions({ width: window.innerWidth, height: window.innerHeight });
    };
    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  // Calculate clip regions - include PDF area (from 0) so PDF-to-EvidenceCard lines can show
  const clipLeft = 0;
  const clipTop = panelBounds.evidenceCards.top;
  const clipRight = panelBounds.argumentAssembly.right;
  const clipBottom = panelBounds.argumentAssembly.bottom;
  const clipWidth = clipRight - clipLeft;
  const clipHeight = clipBottom - clipTop;

  return (
    <svg
      className="fixed inset-0 pointer-events-none z-20"
      width={dimensions.width}
      height={dimensions.height}
    >
      {/* Define clip paths for panel boundaries */}
      <defs>
        <clipPath id="panels-clip">
          <rect
            x={clipLeft}
            y={clipTop}
            width={clipWidth}
            height={clipHeight}
          />
        </clipPath>
      </defs>

      {/* Apply clip path to all connection lines */}
      <g clipPath="url(#panels-clip)">
        {/* 聚焦子论点时：只高亮，不显示连线 */}
        {focusState.type === 'argument' && focusState.id ? (
          <>
            {/* No connection lines when argument is focused - only highlight */}
            {/* Overlay selected snippet's PDF connection line if any */}
            {selectedSnippetId && (
              <SnippetConnectionLines key={`selected-${selectedSnippetId}`} snippetId={selectedSnippetId} />
            )}
          </>
        ) : focusState.type === 'subargument' && focusState.id ? (
          <>
            {/* 聚焦次级子论点时：显示 snippet → 次级子论点 连线 */}
            <SubArgumentConnectionLines key={focusState.id} subArgumentId={focusState.id} />
            {/* Overlay selected snippet's PDF connection line */}
            {selectedSnippetId && (
              <SnippetConnectionLines key={`selected-${selectedSnippetId}`} snippetId={selectedSnippetId} />
            )}
          </>
        ) : focusState.type === 'standard' && focusState.id ? (
          <>
            <StandardConnectionLines key={focusState.id} standardId={focusState.id} />
            {/* Overlay selected snippet's PDF connection line */}
            {selectedSnippetId && (
              <SnippetConnectionLines key={`selected-${selectedSnippetId}`} snippetId={selectedSnippetId} />
            )}
          </>
        ) : selectedSnippetId ? (
          <SnippetConnectionLines key={selectedSnippetId} snippetId={selectedSnippetId} />
        ) : null}
      </g>
    </svg>
  );
}
