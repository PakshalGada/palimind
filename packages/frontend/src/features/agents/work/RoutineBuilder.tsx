import { useEffect, useState } from 'react';
import { api } from '../../../api';
import { Button, Field, Modal, Select, TextArea, TextInput, Toggle } from '../../../ui/primitives';
import type { AgentListItem, Routine, Team } from '../../../types';
import './RoutineBuilder.css';

export default function RoutineBuilder({
  draft,
  agents,
  teams,
  onClose,
  onSaved,
  onError,
}: {
  draft: Partial<Routine> | null;
  agents: AgentListItem[];
  teams: Team[];
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [value, setValue] = useState<Partial<Routine>>(draft || {});
  useEffect(() => setValue(draft || {}), [draft]);
  if (!draft) return null;

  const save = async () => {
    if (!value.name || !value.target_id || !value.input) {
      onError('Name, target and prompt are required.');
      return;
    }
    const payload: Partial<Routine> = {
      ...value,
      target_type: value.target_type || 'agent',
      run_mode: value.run_mode || 'manual',
      tool_pack: value.tool_pack || 'auto',
      enabled: value.enabled ?? true,
    };
    const res = value.id ? await api.routines.update(value.id, payload) : await api.routines.create(payload);
    if (res.error) onError(res.error);
    else onSaved();
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Routine"
      subtitle="Save this work so it can run again on a schedule or on demand."
      width={620}
      footer={
        <div className="ag-modal-foot">
          <Button size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={() => void save()}>
            Save routine
          </Button>
        </div>
      }
    >
      <div className="ag-modal-form">
        <Field label="Name">
          <TextInput value={value.name || ''} onChange={(event) => setValue({ ...value, name: event.target.value })} />
        </Field>
        <div className="ag-modal-grid2">
          <Field label="Target type">
            <Select
              value={value.target_type || 'agent'}
              onChange={(event) =>
                setValue({ ...value, target_type: event.target.value as 'agent' | 'team', target_id: '' })
              }
            >
              <option value="agent">Agent</option>
              <option value="team">Team</option>
            </Select>
          </Field>
          <Field label="Target">
            <Select value={value.target_id || ''} onChange={(event) => setValue({ ...value, target_id: event.target.value })}>
              <option value="">Choose…</option>
              {(value.target_type === 'team' ? teams : agents).map((target) => (
                <option key={target.id} value={target.id}>
                  {(target as Team).display_name || target.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Prompt">
          <TextArea rows={4} value={value.input || ''} onChange={(event) => setValue({ ...value, input: event.target.value })} />
        </Field>
        <div className="ag-modal-grid2">
          <Field label="Trigger">
            <Select
              value={value.run_mode || 'manual'}
              onChange={(event) => setValue({ ...value, run_mode: event.target.value as Routine['run_mode'] })}
            >
              <option value="manual">Manual</option>
              <option value="scheduled">Scheduled (cron)</option>
              <option value="watcher">File watcher</option>
            </Select>
          </Field>
          <Field label="Tool pack">
            <Select
              value={value.tool_pack || 'auto'}
              onChange={(event) => setValue({ ...value, tool_pack: event.target.value as Routine['tool_pack'] })}
            >
              {['auto', 'research', 'code', 'data', 'web', 'custom'].map((pack) => (
                <option key={pack} value={pack}>
                  {pack}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {value.run_mode === 'scheduled' && (
          <Field label="Cron schedule" hint="Minute hour day-of-month month day-of-week · e.g. 0 9 * * 1">
            <TextInput
              value={value.schedule || ''}
              placeholder="0 9 * * 1"
              onChange={(event) => setValue({ ...value, schedule: event.target.value })}
            />
          </Field>
        )}
        {value.run_mode === 'watcher' && (
          <Field label="Watcher glob">
            <TextInput
              value={value.watcher_pattern || ''}
              placeholder="**/*.md"
              onChange={(event) => setValue({ ...value, watcher_pattern: event.target.value })}
            />
          </Field>
        )}
        <Field label="Working root" hint="Optional knowledge base path.">
          <TextInput
            value={value.working_root || ''}
            onChange={(event) => setValue({ ...value, working_root: event.target.value })}
          />
        </Field>
        <Toggle
          title="Enabled"
          description="Paused routines keep their settings."
          checked={value.enabled ?? true}
          onChange={(enabled) => setValue({ ...value, enabled })}
        />
      </div>
    </Modal>
  );
}
