'use client';

import { useRef, useState } from 'react';
import Image from 'next/image';
import {
  Box,
  ImageIcon,
  Save,
  Skull,
  Sparkles,
  Swords,
  Trash2,
  Upload,
  Users,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import {
  apiAssetUrl,
  type CharacterSummary,
  type ConnectionData,
  type RoomData,
} from '@/lib/api';
import { edgeId } from '../editor/graph';
import type { ContentKind, PlacedContainer } from '../types';

export function RoomInspector({ room, connections, rooms, characters, onSave, onUploadImage, onRemoveImage, onAddContent, onEditContainer, onAddRoomFeature, onEditRoomFeature, onRemoveContent, onPlaceCharacter, onStartCombat, onDelete, onSelectConnection }: {
  room: RoomData;
  connections: ConnectionData[];
  rooms: RoomData[];
  characters: CharacterSummary[];
  onSave: (name: string, description: string) => Promise<boolean>;
  onUploadImage: (file: File) => Promise<boolean>;
  onRemoveImage: () => Promise<boolean>;
  onAddContent: (kind: ContentKind) => void;
  onEditContainer: (id: string) => void;
  onAddRoomFeature: () => void;
  onEditRoomFeature: (feature: {
    id: string;
    room_id: string;
    name: string;
    description: string;
    feature_type: string;
  }) => void;
  onRemoveContent: (kind: ContentKind, id: string) => Promise<boolean>;
  onPlaceCharacter: (characterId: number) => Promise<boolean>;
  onStartCombat: () => Promise<boolean>;
  onDelete: () => void;
  onSelectConnection: (connection: ConnectionData) => void;
}) {
  const [name, setName] = useState(room.name);
  const [description, setDescription] = useState(room.description);
  const [characterId, setCharacterId] = useState('');
  const [imageBusy, setImageBusy] = useState(false);
  const [imageError, setImageError] = useState('');
  const imageInput = useRef<HTMLInputElement>(null);
  const attached = connections.filter((connection) => connection.source_room_id === room.id);
  const roomName = (id: string) => rooms.find((item) => item.id === id)?.name || id;
  const selectedCharacter = characters.find((character) => String(character.id) === characterId);
  const roomFeatures = room.room_features ?? [];
  return (
    <>
      <div className="inspector__topline"><span>Selected location</span><Badge variant="outline">{room.counts.players} players</Badge></div>
      <h2>{room.name}</h2>
      <p className="room-id">{room.id}</p>
      <Button className="start-combat-location" onClick={() => void onStartCombat()}>
        <Swords /> Start combat here
      </Button>
      <div className="inspector__section edit-fields">
        <label htmlFor="room-name">Name</label>
        <Input id="room-name" value={name} onChange={(event) => setName(event.target.value)} />
        <label htmlFor="room-description">Description</label>
        <Textarea id="room-description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <Button size="sm" onClick={() => void onSave(name, description)}><Save /> Save details</Button>
      </div>
      <div className="inspector__section room-image-editor">
        <h3>Room image</h3>
        {room.room_image_url ? (
          <div className="room-image-preview">
            <Image
              src={apiAssetUrl(room.room_image_url)}
              alt={`Visual preview for ${room.name}`}
              fill
              sizes="340px"
              unoptimized
              onLoad={() => setImageError('')}
              onError={() => setImageError('The stored image could not be previewed.')}
            />
          </div>
        ) : (
          <div className="room-image-empty"><ImageIcon size={22} /><span>No visual record uploaded</span></div>
        )}
        <input
          ref={imageInput}
          className="room-image-input"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          disabled={imageBusy}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
              setImageError('Choose a PNG, JPEG, or WebP image.');
              event.target.value = '';
              return;
            }
            if (file.size > 8 * 1024 * 1024) {
              setImageError('Room images may be at most 8 MB.');
              event.target.value = '';
              return;
            }
            setImageBusy(true);
            setImageError('');
            const saved = await onUploadImage(file);
            if (!saved) setImageError('The room image could not be saved.');
            setImageBusy(false);
            event.target.value = '';
          }}
        />
        <div className="room-image-actions">
          <Button
            type="button"
            size="sm"
            disabled={imageBusy}
            onClick={() => imageInput.current?.click()}
          >
            <Upload /> {imageBusy ? 'Uploading…' : room.room_image_url ? 'Replace image' : 'Upload image'}
          </Button>
          {room.room_image_url && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={imageBusy}
              onClick={async () => {
                setImageBusy(true);
                setImageError('');
                const removed = await onRemoveImage();
                if (!removed) setImageError('The room image could not be removed.');
                setImageBusy(false);
              }}
            >
              <Trash2 /> Remove
            </Button>
          )}
        </div>
        {imageError && <p className="room-image-error">{imageError}</p>}
        <p className="room-image-help">PNG, JPEG, or WebP · maximum 8 MB</p>
      </div>
      <div className="inspector__section">
        <h3>Outgoing connections <span>{attached.length}</span></h3>
        <ul className="connection-list">
          {attached.map((connection) => (
            <li key={edgeId(connection)}>
              <button onClick={() => onSelectConnection(connection)}>{roomName(connection.destination_room_id)}</button>
              <Badge>{connection.exit_name}</Badge>
            </li>
          ))}
          {!attached.length && <li className="muted-row">No outgoing connections</li>}
        </ul>
      </div>
      <div className="inspector__section character-placement">
        <h3>Place character</h3>
        {characters.length ? (
          <>
            <label htmlFor="character-placement">Character</label>
            <NativeSelect
              id="character-placement"
              value={characterId}
              onChange={(event) => setCharacterId(event.target.value)}
            >
              <NativeSelectOption value="">Choose a character…</NativeSelectOption>
              {characters.map((character) => (
                <NativeSelectOption key={character.id} value={character.id}>
                  {character.name}
                  {character.is_active ? ' · active' : ''}
                  {character.current_room_id ? ` · ${roomName(character.current_room_id)}` : ' · unplaced'}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button
              size="sm"
              disabled={!selectedCharacter || selectedCharacter.current_room_id === room.id}
              onClick={async () => {
                if (selectedCharacter && await onPlaceCharacter(selectedCharacter.id)) {
                  setCharacterId('');
                }
              }}
            >
              <Users />
              {selectedCharacter?.current_room_id === room.id ? 'Already here' : 'Move here'}
            </Button>
          </>
        ) : (
          <p className="muted-row">No selectable characters exist yet.</p>
        )}
      </div>
      <div className="inspector__section content-summary">
        <h3>Room contents</h3>
        {room.players.map((item) => <p key={item.id}><Users size={15} />{item.name}</p>)}
        {room.enemies.map((item) => (
          <p key={item.id}>
            <Skull size={15} />{item.name}
            {item.current_hp !== null && item.max_hp !== null && (
              <strong>{item.current_hp}/{item.max_hp} HP</strong>
            )}
            {item.status !== 'active' && <Badge variant="outline">{item.status}</Badge>}
            <button className="remove-content" type="button" title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`} onClick={() => void onRemoveContent('enemy', item.id)}><Trash2 size={14} /></button>
          </p>
        ))}
        {room.loose_items.map((item) => <p key={item.id}><Sparkles size={15} />{item.name}<strong>×{item.quantity}</strong><button className="remove-content" type="button" title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`} onClick={() => void onRemoveContent('item', item.id)}><Trash2 size={14} /></button></p>)}
        {(room.containers as PlacedContainer[]).map((item) => (
          <p key={item.id}>
            <Button type="button" variant="ghost" size="sm" onClick={() => onEditContainer(item.id)}>
              <Box size={15} />{item.name}
            </Button>
            {item.is_locked && <strong>Locked</strong>}
            {item.is_broken && <strong>Broken lock</strong>}
            {item.hidden && <strong>Hidden · DC {item.discovery_difficulty ?? '?'}</strong>}
            <strong>{item.item_count} items</strong>
            <button className="remove-content" type="button" title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`} onClick={() => void onRemoveContent('container', item.id)}><Trash2 size={14} /></button>
          </p>
        ))}
        <h4>Room Features</h4>
        {roomFeatures.map((feature) => (
          <p key={feature.id}>
            <Button type="button" variant="ghost" size="sm" onClick={() => onEditRoomFeature(feature)}>
              <Sparkles size={15} />{feature.name}
            </Button>
            <Badge variant="outline">{feature.feature_type}</Badge>
          </p>
        ))}
        {!roomFeatures.length && <p className="muted-row">No room features.</p>}
        {!room.players.length && !room.enemies.length && !room.loose_items.length && !room.containers.length && !roomFeatures.length && <p className="muted-row">This location is empty.</p>}
      </div>
      <div className="inspector__actions">
        <Button variant="outline" onClick={() => onAddContent('enemy')}>Add enemy</Button>
        <Button variant="outline" onClick={() => onAddContent('item')}>Add item</Button>
        <Button variant="outline" onClick={() => onAddContent('container')}>Add container</Button>
        <Button variant="outline" onClick={onAddRoomFeature}>Add feature</Button>
      </div>
      <Button className="delete-location" variant="ghost" onClick={onDelete}><Trash2 /> Delete location</Button>
    </>
  );
}
