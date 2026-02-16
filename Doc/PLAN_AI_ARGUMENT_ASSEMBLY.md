# AI Argument Assembly Implementation Plan

## Overview
Implement a one-click AI-powered argument assembly system that:
1. Analyzes snippets to extract entities and relationships
2. Groups snippets by subject (person name) then by achievement type
3. Generates structured Arguments from grouped snippets
4. Auto-maps Arguments to EB-1A Standards

## Current State Analysis

### Existing Capabilities
- `relationship_analyzer.py` - Entity extraction from snippets
- `snippet_linker.py` - Derives snippet associations from entity graph
- `llm_client.py` - OpenAI integration (gpt-4o)
- Frontend `ArgumentAssembly.tsx` - UI component for displaying arguments
- `AppContext.tsx` - State management with `arguments` and `argumentMappings`

### Missing Components
- Backend Argument persistence API
- Argument generation pipeline orchestration
- Standard auto-mapping logic

---

## Implementation Steps

### Phase 1: Backend - Argument Generation Pipeline

#### 1.1 Create Argument Generator Service
**File:** `backend/app/services/argument_generator.py`

```python
# Responsibilities:
# - Orchestrate entity extraction → grouping → argument generation
# - Use relationship_analyzer to get entities per snippet
# - Group snippets: first by person name, then by achievement type
# - Call LLM to generate argument title and summary from grouped snippets
# - Auto-map to standards using achievement type keywords
```

Key functions:
- `generate_arguments_from_snippets(project_id, snippets)` - Main entry point
- `extract_and_group_snippets(snippets)` - Entity-based grouping
- `generate_argument_content(grouped_snippets)` - LLM call for title/summary
- `map_argument_to_standard(argument)` - Keyword-based standard mapping

#### 1.2 Create Argument API Endpoints
**File:** `backend/app/routers/arguments.py`

Endpoints:
- `POST /api/projects/{project_id}/arguments/generate` - Trigger one-click generation
- `GET /api/projects/{project_id}/arguments` - List arguments
- `PUT /api/projects/{project_id}/arguments/{id}` - Update argument
- `DELETE /api/projects/{project_id}/arguments/{id}` - Delete argument
- `POST /api/projects/{project_id}/arguments/{id}/mappings` - Add standard mapping

#### 1.3 Argument Data Model
**File:** `backend/app/models/argument.py`

```python
class Argument:
    id: str
    project_id: str
    title: str
    summary: str
    snippet_ids: List[str]
    subject_name: str  # Person the argument is about
    achievement_type: str  # Category (awards, publications, etc.)
    created_at: datetime
    updated_at: datetime

class ArgumentMapping:
    id: str
    argument_id: str  # source
    standard_id: str  # target
    confidence: float  # AI confidence score
    is_confirmed: bool  # User confirmed
```

### Phase 2: AI Logic - Grouping & Generation

#### 2.1 Subject-Achievement Grouping Algorithm
```
Input: List of snippets with extracted entities

Step 1: Extract entities from each snippet
  - Person names (PERSON entities)
  - Achievement indicators (AWARD, PUBLICATION, MEMBERSHIP, etc.)

Step 2: Group by primary subject
  - Identify main subject (most frequently mentioned person)
  - Create subject buckets

Step 3: Sub-group by achievement type
  - Within each subject bucket, group by achievement category
  - Categories align with EB-1A criteria

Step 4: Generate arguments
  - Each (subject, achievement_type) pair becomes one Argument
  - LLM generates title and summary from grouped snippets
```

#### 2.2 Standard Auto-Mapping Rules
```
Achievement Type → EB-1A Standard Mapping:
- "award", "prize", "honor" → standard-1 (Awards)
- "membership", "association", "fellow" → standard-2 (Membership)
- "publication", "article", "press" → standard-3 (Published Material)
- "judge", "review", "evaluate" → standard-4 (Judging)
- "contribution", "impact", "original" → standard-5 (Original Contributions)
- "author", "scholarly", "journal" → standard-6 (Scholarly Articles)
- "exhibition", "showcase", "display" → standard-7 (Exhibitions)
- "leading", "critical", "distinguished" → standard-8 (Leading Role)
- "salary", "remuneration", "compensation" → standard-9 (High Salary)
- "commercial", "success", "revenue" → standard-10 (Commercial Success)
```

### Phase 3: Frontend Integration

#### 3.1 Add Generate Button to ArgumentAssembly
**File:** `frontend/src/components/ArgumentAssembly.tsx`

- Add "Generate Arguments" button in header
- Show loading state during generation
- Display generated arguments in list
- Allow manual editing/deletion

#### 3.2 Update AppContext for API Integration
**File:** `frontend/src/context/AppContext.tsx`

- Add `generateArguments()` function
- Add `isGeneratingArguments` loading state
- Connect to backend API

#### 3.3 UI Flow
```
1. User clicks "Generate Arguments" button
2. Show loading spinner with "Analyzing snippets..."
3. Backend processes snippets → generates arguments → auto-maps
4. Frontend receives arguments and mappings
5. Display in ArgumentAssembly panel
6. Connection lines update automatically
```

### Phase 4: Connection Line Boundary Fix

#### 4.1 Fix Vertical Boundary Clipping
**File:** `frontend/src/components/ConnectionLines.tsx`

- Add viewport boundary checking
- Clamp connection endpoints to visible area
- Handle cases where elements are scrolled out of view

---

## File Changes Summary

### New Files
1. `backend/app/services/argument_generator.py`
2. `backend/app/routers/arguments.py`
3. `backend/app/models/argument.py`

### Modified Files
1. `backend/app/main.py` - Register arguments router
2. `frontend/src/components/ArgumentAssembly.tsx` - Add generate button
3. `frontend/src/context/AppContext.tsx` - Add generation functions
4. `frontend/src/components/ConnectionLines.tsx` - Fix boundary issues

---

## Testing Plan
1. Test entity extraction with sample snippets
2. Verify grouping logic with multi-subject documents
3. Test standard mapping accuracy
4. Verify connection line rendering at boundaries
5. End-to-end: Upload document → Extract → Generate → View mappings
