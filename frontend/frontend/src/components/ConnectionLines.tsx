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

// Connection lines for a focused snippet (PDF → Card → Argument)
function SnippetConnectionLines({ snippetId }: { snippetId: string }) {
  const {
    snippetPositions, pdfBboxPositions, allSnippets,
    arguments: arguments_, argumentPositions
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

  // Find arguments that contain this snippet
  const relatedArguments = arguments_.filter(arg => arg.snippetIds?.includes(snippetId));

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

      {/* 2. Evidence Card RIGHT side → Argument(s) LEFT side */}
      {cardPos && relatedArguments.map(arg => {
        const argPos = argumentPositions.get(arg.id);
        if (!argPos) return null;
        return (
          <CurvedLine
            key={`snippet-arg-${arg.id}`}
            startX={cardRightX}
            startY={cardY}
            endX={argPos.x - (argPos.width || 0)} // Connect to LEFT side of argument
            endY={argPos.y}
            color={color}
            strokeWidth={2}
          />
        );
      })}
    </g>
  );
}

// Connection lines for a focused Argument (show Snippet → Argument connections)
function ArgumentConnectionLines({ argumentId }: { argumentId: string }) {
  const {
    allSnippets, snippetPositions,
    arguments: arguments_, argumentPositions
  } = useApp();

  const argument = arguments_.find(a => a.id === argumentId);
  const argPos = argumentPositions.get(argumentId);

  if (!argument || !argPos) return null;

  // Get all snippets in this argument
  const snippetIds = argument.snippetIds || [];

  // Calculate argument LEFT edge (argPos.x is right edge)
  const argLeftX = argPos.x - (argPos.width || 0);

  // Get the standard color from argument's standardKey
  const standardColor = argument.standardKey ? getStandardKeyColor(argument.standardKey) : '#3b82f6';

  return (
    <g>
      {/* Snippet → Argument connections */}
      {snippetIds.map(snippetId => {
        const snippet = allSnippets.find(s => s.id === snippetId);
        const cardPos = snippetPositions.get(snippetId);
        if (!snippet || !cardPos) return null;

        return (
          <CurvedLine
            key={`arg-snip-${snippetId}`}
            startX={cardPos.x} // Right side of snippet card
            startY={cardPos.y}
            endX={argLeftX} // Left side of argument
            endY={argPos.y}
            color={standardColor}
            strokeWidth={2.5}
            glow={true}
          />
        );
      })}
    </g>
  );
}

// Connection lines for a focused Standard (show Snippet → Argument connections for that standard)
function StandardConnectionLines({ standardId }: { standardId: string }) {
  const {
    allSnippets, snippetPositions,
    arguments: arguments_, argumentPositions, argumentMappings
  } = useApp();

  // Find the standardKey that maps to this standardId (reverse lookup)
  const STANDARD_KEY_TO_ID: Record<string, string> = {
    'awards': 'std-awards',
    'membership': 'std-membership',
    'scholarly_articles': 'std-scholarly',
    'judging': 'std-judging',
    'original_contribution': 'std-contribution',
    'leading_role': 'std-leading',
    'high_salary': 'std-salary',
    'published_material': 'std-published',
  };

  const standardKeyEntry = Object.entries(STANDARD_KEY_TO_ID).find(
    ([, id]) => id === standardId
  );
  const standardKey = standardKeyEntry ? standardKeyEntry[0] : null;

  // Find all arguments mapped to this standard (both AI-generated and manual)
  const mappedArgumentIds = new Set<string>();

  // 1. AI-generated standardKey mappings
  arguments_.forEach(arg => {
    if (arg.standardKey && STANDARD_KEY_TO_ID[arg.standardKey] === standardId) {
      mappedArgumentIds.add(arg.id);
    }
  });

  // 2. Manual drag-drop mappings
  argumentMappings.filter(m => m.target === standardId).forEach(m => {
    mappedArgumentIds.add(m.source);
  });

  const mappedArguments = arguments_.filter(arg => mappedArgumentIds.has(arg.id));

  // Get the standard color
  const standardColor = standardKey ? getStandardKeyColor(standardKey) : '#3b82f6';

  return (
    <g>
      {mappedArguments.map(arg => {
        const argPos = argumentPositions.get(arg.id);
        if (!argPos) return null;

        const argLeftX = argPos.x - (argPos.width || 0);
        const snippetIds = arg.snippetIds || [];

        return (
          <g key={`std-arg-group-${arg.id}`}>
            {/* Snippet → Argument connections */}
            {snippetIds.map(snippetId => {
              const snippet = allSnippets.find(s => s.id === snippetId);
              const cardPos = snippetPositions.get(snippetId);
              if (!snippet || !cardPos) return null;

              return (
                <CurvedLine
                  key={`std-snip-arg-${snippetId}`}
                  startX={cardPos.x} // Right side of snippet card
                  startY={cardPos.y}
                  endX={argLeftX} // Left side of argument
                  endY={argPos.y}
                  color={standardColor}
                  strokeWidth={2}
                  glow={false}
                />
              );
            })}
          </g>
        );
      })}
    </g>
  );
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
        {focusState.type === 'argument' && focusState.id ? (
          <ArgumentConnectionLines key={focusState.id} argumentId={focusState.id} />
        ) : focusState.type === 'standard' && focusState.id ? (
          <StandardConnectionLines key={focusState.id} standardId={focusState.id} />
        ) : selectedSnippetId ? (
          <SnippetConnectionLines key={selectedSnippetId} snippetId={selectedSnippetId} />
        ) : null}
      </g>
    </svg>
  );
}
