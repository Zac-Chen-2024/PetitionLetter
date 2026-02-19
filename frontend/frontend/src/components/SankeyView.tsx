import { useMemo, useRef, useEffect, useState } from 'react';
import { sankey, sankeyLinkHorizontal } from 'd3-sankey';
import type { SankeyNode, SankeyLink } from 'd3-sankey';
import { useApp } from '../context/AppContext';
import { legalStandards } from '../data/legalStandards';

interface SankeyNodeData {
  id: string;
  name: string;
  color: string;
  type: 'argument' | 'standard';
  snippetCount?: number;
}

interface SankeyLinkData {
  source: string;
  target: string;
  value: number;
  connectionId: string;
  isConfirmed: boolean;
}

type SNode = SankeyNode<SankeyNodeData, SankeyLinkData>;
type SLink = SankeyLink<SankeyNodeData, SankeyLinkData>;

export function SankeyView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const {
    arguments: arguments_,
    argumentMappings,
    focusState,
    setFocusState,
  } = useApp();

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const { width, height } = containerRef.current.getBoundingClientRect();
        setDimensions({ width: width - 40, height: height - 40 }); // padding
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  // Build sankey data from Arguments -> Standards
  const sankeyData = useMemo(() => {
    const nodeIds = new Set<string>();
    const nodes: SankeyNodeData[] = [];
    const links: SankeyLinkData[] = [];

    // Add argument nodes (left side)
    arguments_.forEach((arg) => {
      nodeIds.add(arg.id);
      const title = arg.title || 'Untitled';
      nodes.push({
        id: arg.id,
        name: title.slice(0, 25) + (title.length > 25 ? '...' : ''),
        color: '#3b82f6', // Blue for arguments
        type: 'argument',
        snippetCount: (arg.snippetIds || []).length,
      });
    });

    // Add standard nodes (right side)
    legalStandards.forEach((standard) => {
      nodeIds.add(standard.id);
      nodes.push({
        id: standard.id,
        name: standard.shortName,
        color: standard.color,
        type: 'standard',
      });
    });

    // Add links from argumentMappings
    argumentMappings.forEach(mapping => {
      // Only add link if both nodes exist
      if (nodeIds.has(mapping.source) && nodeIds.has(mapping.target)) {
        links.push({
          source: mapping.source,  // argumentId
          target: mapping.target,  // standardId
          value: 1,
          connectionId: mapping.id,
          isConfirmed: mapping.isConfirmed,
        });
      }
    });

    return { nodes, links };
  }, [arguments_, argumentMappings]);

  // Generate sankey layout
  const { nodes, links } = useMemo(() => {
    if (sankeyData.nodes.length === 0) {
      return { nodes: [] as SNode[], links: [] as SLink[] };
    }

    const sankeyGenerator = sankey<SankeyNodeData, SankeyLinkData>()
      .nodeId(d => d.id)
      .nodeWidth(20)
      .nodePadding(12)
      .extent([[20, 20], [dimensions.width - 20, dimensions.height - 20]]);

    const { nodes, links } = sankeyGenerator({
      nodes: sankeyData.nodes.map(d => ({ ...d })),
      links: sankeyData.links.map(d => ({ ...d })),
    });

    return { nodes, links };
  }, [sankeyData, dimensions]);

  // Generate link path
  const linkPath = sankeyLinkHorizontal<SNode, SLink>();

  // Check if element is highlighted
  const isNodeHighlighted = (node: SNode) => {
    if (focusState.type === 'none') return true;

    const nodeData = node as SNode & SankeyNodeData;

    if (focusState.type === 'standard') {
      if (nodeData.type === 'standard') {
        return nodeData.id === focusState.id;
      }
      // Argument is highlighted if mapped to focused standard
      return argumentMappings.some(
        m => m.target === focusState.id && m.source === nodeData.id
      );
    }

    // For argument focus (if we add this focus type later)
    return true;
  };

  const isLinkHighlighted = (link: SLink) => {
    if (focusState.type === 'none') return true;

    const targetNode = link.target as SNode & SankeyNodeData;

    if (focusState.type === 'standard') {
      return targetNode.id === focusState.id;
    }

    return true;
  };

  const handleNodeClick = (node: SNode & SankeyNodeData) => {
    if (node.type === 'standard') {
      setFocusState({ type: 'standard', id: node.id });
    }
    // Arguments don't have a focus state in the current design
  };

  const handleLinkClick = (_linkData: SankeyLinkData) => {
    // Argument mappings are always confirmed, no need to confirm
  };

  return (
    <div ref={containerRef} className="h-full w-full overflow-hidden p-4">
      <svg width={dimensions.width} height={dimensions.height} className="overflow-visible">
        {/* Links */}
        <g>
          {links.map((link, i) => {
            const sourceNode = link.source as SNode & SankeyNodeData;
            const targetNode = link.target as SNode & SankeyNodeData;
            const highlighted = isLinkHighlighted(link);
            const path = linkPath(link);

            // Find the original link data by matching source and target IDs
            // (don't rely on index as d3-sankey may reorder links)
            const originalLink = sankeyData.links.find(
              l => l.source === sourceNode.id && l.target === targetNode.id
            );
            if (!originalLink) return null;

            return (
              <g key={originalLink.connectionId}>
                <path
                  d={path || ''}
                  fill="none"
                  stroke={sourceNode.color}
                  strokeWidth={Math.max(link.width || 1, 4)}
                  strokeOpacity={highlighted ? 0.5 : 0.05}
                  strokeDasharray={originalLink.isConfirmed ? undefined : '8 4'}
                  className="transition-all duration-200 cursor-pointer hover:stroke-opacity-70"
                  onClick={() => handleLinkClick(originalLink)}
                />
                {/* Confirmed indicator */}
                {originalLink.isConfirmed && highlighted && (
                  <circle
                    cx={(((link.source as SNode).x1 ?? 0) + ((link.target as SNode).x0 ?? 0)) / 2}
                    cy={link.y0 ?? 0}
                    r={6}
                    fill={sourceNode.color}
                    className="pointer-events-none"
                  >
                    <title>Confirmed</title>
                  </circle>
                )}
              </g>
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {nodes.map((node, i) => {
            const nodeData = node as SNode & SankeyNodeData;
            const highlighted = isNodeHighlighted(node);
            const isFocused =
              (focusState.type === 'standard' && nodeData.type === 'standard' && nodeData.id === focusState.id);

            return (
              <g
                key={i}
                className="cursor-pointer"
                onClick={() => handleNodeClick(nodeData)}
                style={{ opacity: highlighted ? 1 : 0.1 }}
              >
                {/* Node rectangle */}
                <rect
                  x={node.x0 ?? 0}
                  y={node.y0 ?? 0}
                  width={(node.x1 ?? 0) - (node.x0 ?? 0)}
                  height={(node.y1 ?? 0) - (node.y0 ?? 0)}
                  fill={nodeData.color}
                  rx={4}
                  className={`transition-all duration-200 ${isFocused ? 'stroke-2 stroke-slate-800' : ''}`}
                />

                {/* Node label */}
                <text
                  x={nodeData.type === 'argument' ? (node.x0 || 0) - 8 : (node.x1 || 0) + 8}
                  y={((node.y0 || 0) + (node.y1 || 0)) / 2}
                  dy="0.35em"
                  textAnchor={nodeData.type === 'argument' ? 'end' : 'start'}
                  className="text-xs fill-slate-700 pointer-events-none"
                  style={{
                    fontWeight: isFocused ? 600 : 400,
                    fontSize: nodeData.type === 'standard' ? '12px' : '10px'
                  }}
                >
                  {nodeData.name}
                  {nodeData.type === 'argument' && nodeData.snippetCount ? ` (${nodeData.snippetCount})` : ''}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Legend */}
      <div className="absolute bottom-6 left-6 flex items-center gap-6 text-xs text-slate-500 bg-white/80 backdrop-blur-sm px-3 py-2 rounded-lg">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-blue-500 rounded" />
          <span>Arguments</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-8 h-1 bg-blue-400 rounded" />
          <span>Argument → Standard Mapping</span>
        </div>
      </div>
    </div>
  );
}
