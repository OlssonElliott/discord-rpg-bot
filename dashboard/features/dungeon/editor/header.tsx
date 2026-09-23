'use client';

import { Box, Map, Plus, Skull, Sparkles, Swords, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { AreaSummary } from '@/lib/api';

type WorkspaceMode = 'locations' | 'characters' | 'combat';

type EditorHeaderProps = {
  workspaceMode: WorkspaceMode;
  areas: AreaSummary[];
  areaId: string;
  notice: string;
  hasCombatScene: boolean;
  combatBusy: boolean;
  onWorkspaceModeChange: (mode: WorkspaceMode) => void;
  onAreaChange: (areaId: string) => void;
  onAddArea: () => void;
  onOpenItemLibrary: () => void;
  onOpenFeatureLibrary: () => void;
  onOpenEnemyLibrary: () => void;
  onAddRoom: () => void;
  onAddCombatLandmark: () => void;
};

export function EditorHeader({
  workspaceMode,
  areas,
  areaId,
  notice,
  hasCombatScene,
  combatBusy,
  onWorkspaceModeChange,
  onAreaChange,
  onAddArea,
  onOpenItemLibrary,
  onOpenFeatureLibrary,
  onOpenEnemyLibrary,
  onAddRoom,
  onAddCombatLandmark,
}: EditorHeaderProps) {
  return (
    <header className="editor-header">
      <div className="brand-mark">
        {workspaceMode === 'locations' ? (
          <Map size={19} />
        ) : workspaceMode === 'characters' ? (
          <Users size={19} />
        ) : (
          <Swords size={19} />
        )}
      </div>
      <div className="editor-title">
        <p className="kicker">DM workspace</p>
        <h1>
          {workspaceMode === 'locations'
            ? 'Location editor'
            : workspaceMode === 'characters'
              ? 'Characters'
              : 'Combat'}
        </h1>
      </div>
      <nav className="workspace-tabs" aria-label="DM workspace">
        <button
          type="button"
          className={workspaceMode === 'locations' ? 'active' : ''}
          onClick={() => onWorkspaceModeChange('locations')}
        >
          <Map size={14} /> Locations
        </button>
        <button
          type="button"
          className={workspaceMode === 'characters' ? 'active' : ''}
          onClick={() => onWorkspaceModeChange('characters')}
        >
          <Users size={14} /> Characters
        </button>
        <button
          type="button"
          className={workspaceMode === 'combat' ? 'active' : ''}
          onClick={() => onWorkspaceModeChange('combat')}
        >
          <Swords size={14} /> Combat
        </button>
      </nav>
      {workspaceMode !== 'characters' && (
        <NativeSelect
          aria-label="Current area"
          className="area-select"
          value={areaId}
          onChange={(event) => onAreaChange(event.target.value)}
        >
          {areas.map((area) => (
            <NativeSelectOption key={area.id} value={area.id}>
              {area.name} · {area.room_count} locations
            </NativeSelectOption>
          ))}
        </NativeSelect>
      )}
      {workspaceMode === 'locations' && (
        <>
          <Button variant="outline" size="sm" onClick={onAddArea}>
            <Plus /> Area
          </Button>
          <Button variant="outline" size="sm" onClick={onOpenItemLibrary}>
            <Box /> Item library
          </Button>
          <Button variant="outline" size="sm" onClick={onOpenFeatureLibrary}>
            <Sparkles /> Feature library
          </Button>
        </>
      )}
      {workspaceMode !== 'characters' && (
        <Button variant="outline" size="sm" onClick={onOpenEnemyLibrary}>
          <Skull /> Enemy library
        </Button>
      )}
      <div className="header-status"><span /> {notice || 'Saved'}</div>
      {workspaceMode === 'locations' && (
        <Button className="add-location" onClick={onAddRoom} disabled={!areaId}>
          <Plus /> Add location
        </Button>
      )}
      {workspaceMode === 'combat' && hasCombatScene && (
        <Button
          className="add-location"
          onClick={onAddCombatLandmark}
          disabled={combatBusy}
        >
          <Plus /> Add landmark
        </Button>
      )}
    </header>
  );
}
