import { useRef, useState } from 'react';
import { Shuffle, Upload, X } from 'lucide-react';
import AgentAvatar from '../../components/AgentAvatar';
import { Button, SegmentedControl, Toggle } from '../../ui/primitives';
import {
  BOT_COLORS,
  BOT_GLASSES,
  BOT_HATS,
  BOT_LABELS,
  BOT_PALETTE,
  BOT_PRESETS,
  BOT_SHADINGS,
  BOT_TYPES,
  randomBotConfig,
  type BotAvatarConfig,
  type BotGlasses,
  type BotHat,
  type BotShading,
  type BotType,
} from '../../bots/config';

export interface AvatarValue {
  avatar_type?: 'bot' | 'upload';
  avatar_upload?: string;
  avatar_config?: BotAvatarConfig;
}

type Mode = 'generate' | 'preset' | 'upload';
type Option<T extends string> = { value: T; label: string };

const SHADING_LABELS: Record<BotShading, string> = {
  fabric: 'Plush',
  plastic: 'Plastic',
  smooth: 'Smooth',
  crisp: 'Crisp',
  flat: 'Flat',
};
const HAT_LABELS: Record<BotHat, string> = {
  none: 'None',
  beanie: 'Beanie',
  party: 'Party',
  crown: 'Crown',
  beret: 'Beret',
  tophat: 'Top hat',
};
const GLASSES_LABELS: Record<BotGlasses, string> = {
  none: 'None',
  round: 'Round',
  square: 'Square',
  shades: 'Shades',
};

const shadingOptions: Option<BotShading>[] = BOT_SHADINGS.map((v) => ({ value: v, label: SHADING_LABELS[v] }));
const hatOptions: Option<BotHat>[] = BOT_HATS.map((v) => ({ value: v, label: HAT_LABELS[v] }));
const glassesOptions: Option<BotGlasses>[] = BOT_GLASSES.map((v) => ({ value: v, label: GLASSES_LABELS[v] }));
const faceOptions: Option<'eyes' | 'mouth'>[] = [
  { value: 'eyes', label: 'Eyes' },
  { value: 'mouth', label: 'Mouth' },
];

function PickerRow<T extends string>({
  label,
  value,
  options,
  onPick,
}: {
  label: string;
  value: T;
  options: Option<T>[];
  onPick: (value: T) => void;
}) {
  return (
    <div className="ax-avatar__picker">
      <span className="ax-avatar__picker-label">{label}</span>
      <div className="ax-avatar__picker-options">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            className={`ax-pickchip${o.value === value ? ' is-on' : ''}`}
            onClick={() => onPick(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="ax-avatar__slider">
      <span className="ax-avatar__slider-label">
        {label}
        <span>{Number.isInteger(value) ? value : value.toFixed(2)}</span>
      </span>
      <input
        type="range"
        className="ax-range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </label>
  );
}

/**
 * Avatar builder powered by the vendored "bots" library: 18 plush 3D shapes,
 * living faces, three states, materials, hats, glasses, headphones and bow
 * ties — plus image upload. All rendering happens locally on a 2D canvas.
 */
export default function AvatarCustomizer({
  value,
  onChange,
}: {
  value: AvatarValue;
  onChange: (patch: AvatarValue) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>(value.avatar_type === 'upload' ? 'upload' : 'generate');
  const [presetId, setPresetId] = useState<string | null>(null);

  const config = value.avatar_config || {};
  const type = config.type || 'clover';
  const color = config.color || BOT_PALETTE[type] || '#41C4FF';
  const shading = config.shading || 'fabric';
  const hat = config.hat || 'none';
  const glasses = config.glasses || 'none';
  const face = config.face || 'eyes';
  const fabric = shading === 'fabric';
  const dLight = fabric ? 295 : 300;
  const dShadow = fabric ? 1.15 : 0.6;
  const dHighlight = fabric ? 1.2 : 1.3;
  const dRim = fabric ? 0.6 : 0.5;

  const patchConfig = (patch: BotAvatarConfig) => {
    setPresetId(null);
    onChange({ avatar_type: 'bot', avatar_config: { ...config, ...patch } });
  };

  const changeMode = (next: Mode) => {
    setMode(next);
    onChange({ avatar_type: next === 'upload' ? 'upload' : 'bot' });
  };

  const pickType = (next: BotType) => {
    const wasDefault = !config.color || config.color === BOT_PALETTE[type];
    patchConfig({ type: next, ...(wasDefault ? { color: BOT_PALETTE[next] } : {}) });
  };

  const shuffle = () => {
    setPresetId(null);
    onChange({ avatar_type: 'bot', avatar_config: randomBotConfig() });
  };

  const applyPreset = (id: string) => {
    const preset = BOT_PRESETS.find((p) => p.id === id);
    if (!preset) return;
    setPresetId(id);
    onChange({ avatar_type: 'bot', avatar_config: { ...preset.config } });
  };

  const onUpload = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        onChange({ avatar_type: 'upload', avatar_upload: reader.result });
      }
    };
    reader.readAsDataURL(file);
  };

  return (
    <div className="ax-avatar">
      <div className="ax-avatar__preview">
        <div className="ax-avatar__stage">
          <AgentAvatar
            config={config}
            type={mode === 'upload' ? 'upload' : 'bot'}
            upload={value.avatar_upload}
            size={120}
          />
        </div>
        <div className="ax-avatar__preview-body">
          <SegmentedControl<Mode>
            value={mode}
            onChange={changeMode}
            options={[
              { value: 'generate', label: 'Generate' },
              { value: 'preset', label: 'Presets' },
              { value: 'upload', label: 'Upload' },
            ]}
          />
          <p className="ax-avatar__hint">
            {mode === 'generate'
              ? 'A living 3D-style bot. Hover it — the eyes follow your pointer and a click makes it hop.'
              : mode === 'preset'
                ? 'Start from a ready-made character, then fine-tune it.'
                : 'Bring your own image (stored locally).'}
          </p>
        </div>
      </div>

      {mode === 'generate' && (
        <div className="ax-avatar__panel">
          <div className="ax-avatar__row">
            <Button size="sm" onClick={shuffle}>
              <Shuffle size={13} /> Shuffle
            </Button>
          </div>

          <div className="ax-avatar__picker">
            <span className="ax-avatar__picker-label">Shape</span>
            <div className="ax-avatar__types">
              {BOT_TYPES.map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`ax-bot-type${t === type ? ' is-on' : ''}`}
                  onClick={() => pickType(t)}
                >
                  <span className="ax-bot-type__dot" style={{ background: BOT_PALETTE[t] }} />
                  <span>{BOT_LABELS[t]}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="ax-avatar__picker">
            <span className="ax-avatar__picker-label">Colour</span>
            <div className="ax-avatar__swatches">
              {BOT_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`ax-swatch${c === color ? ' is-on' : ''}`}
                  style={{ background: c }}
                  title={c}
                  onClick={() => patchConfig({ color: c })}
                />
              ))}
              <label className="ax-swatch ax-swatch--custom" title="Custom colour">
                <input type="color" value={color} onChange={(e) => patchConfig({ color: e.target.value })} />
              </label>
            </div>
          </div>

          <PickerRow
            label="Material"
            value={shading}
            options={shadingOptions}
            onPick={(v) => patchConfig({ shading: v })}
          />
          <PickerRow label="Face" value={face} options={faceOptions} onPick={(v) => patchConfig({ face: v })} />
          <PickerRow label="Hat" value={hat} options={hatOptions} onPick={(v) => patchConfig({ hat: v })} />
          <PickerRow
            label="Glasses"
            value={glasses}
            options={glassesOptions}
            onPick={(v) => patchConfig({ glasses: v })}
          />

          <div className="ax-avatar__toggles">
            <Toggle
              title="Headphones"
              checked={!!config.headphones}
              onChange={(v) => patchConfig({ headphones: v })}
            />
            <Toggle title="Bow tie" checked={!!config.bowTie} onChange={(v) => patchConfig({ bowTie: v })} />
            <Toggle title="Blush" checked={!!config.blush} onChange={(v) => patchConfig({ blush: v })} />
            <Toggle
              title="Eye shine"
              checked={config.eyeShine !== false}
              onChange={(v) => patchConfig({ eyeShine: v })}
            />
          </div>

          <div className="ax-avatar__sliders">
            <SliderRow
              label="Speed"
              value={config.speed ?? 1}
              min={0.2}
              max={3}
              step={0.05}
              onChange={(v) => patchConfig({ speed: v })}
            />
            <SliderRow
              label="Eye size"
              value={config.eyeSize ?? 1}
              min={0.5}
              max={1.8}
              step={0.01}
              onChange={(v) => patchConfig({ eyeSize: v })}
            />
            <SliderRow
              label="Eye gap"
              value={config.eyeGap ?? 1}
              min={0.5}
              max={1.6}
              step={0.01}
              onChange={(v) => patchConfig({ eyeGap: v })}
            />
            <SliderRow
              label="Face size"
              value={config.faceScale ?? 1}
              min={0.6}
              max={1.5}
              step={0.01}
              onChange={(v) => patchConfig({ faceScale: v })}
            />
            <SliderRow
              label="Brightness"
              value={config.brightness ?? 1}
              min={0.3}
              max={2}
              step={0.01}
              onChange={(v) => patchConfig({ brightness: v })}
            />
            <SliderRow
              label="Saturation"
              value={config.saturation ?? 1}
              min={0}
              max={2.5}
              step={0.01}
              onChange={(v) => patchConfig({ saturation: v })}
            />
          </div>

          <details className="ax-advanced">
            <summary>Advanced</summary>
            <div className="ax-avatar__sliders">
              <SliderRow
                label="Look around"
                value={config.turn ?? 1}
                min={0}
                max={2}
                step={0.01}
                onChange={(v) => patchConfig({ turn: v })}
              />
              <SliderRow
                label="Jump every (s)"
                value={config.jumpEvery ?? 8}
                min={0}
                max={20}
                step={0.5}
                onChange={(v) => patchConfig({ jumpEvery: v })}
              />
              <SliderRow
                label="Light angle"
                value={config.light ?? dLight}
                min={0}
                max={360}
                step={1}
                onChange={(v) => patchConfig({ light: v })}
              />
              <SliderRow
                label="Shadow"
                value={config.shadow ?? dShadow}
                min={0}
                max={2}
                step={0.01}
                onChange={(v) => patchConfig({ shadow: v })}
              />
              <SliderRow
                label="Highlight"
                value={config.highlight ?? dHighlight}
                min={0}
                max={2}
                step={0.01}
                onChange={(v) => patchConfig({ highlight: v })}
              />
              <SliderRow
                label="Rim light"
                value={config.rim ?? dRim}
                min={0}
                max={2}
                step={0.01}
                onChange={(v) => patchConfig({ rim: v })}
              />
              <SliderRow
                label="Light spread"
                value={config.spread ?? 1.4}
                min={0.4}
                max={2.5}
                step={0.01}
                onChange={(v) => patchConfig({ spread: v })}
              />
              <SliderRow
                label="Depth"
                value={config.depth ?? 0.65}
                min={0.2}
                max={2}
                step={0.01}
                onChange={(v) => patchConfig({ depth: v })}
              />
              <SliderRow
                label="Fur length"
                value={config.furLength ?? 1}
                min={0.3}
                max={2.5}
                step={0.01}
                onChange={(v) => patchConfig({ furLength: v })}
              />
              <SliderRow
                label="Fur density"
                value={config.furDensity ?? 1.6}
                min={0.3}
                max={2}
                step={0.01}
                onChange={(v) => patchConfig({ furDensity: v })}
              />
              <SliderRow
                label="Fur fuzz"
                value={config.furFuzz ?? 0.9}
                min={0}
                max={1}
                step={0.01}
                onChange={(v) => patchConfig({ furFuzz: v })}
              />
              <SliderRow
                label="Fur curl"
                value={config.furCurl ?? 0.7}
                min={0}
                max={1}
                step={0.01}
                onChange={(v) => patchConfig({ furCurl: v })}
              />
              <SliderRow
                label="Fur gravity"
                value={config.furGravity ?? 0.9}
                min={0}
                max={1}
                step={0.01}
                onChange={(v) => patchConfig({ furGravity: v })}
              />
            </div>
          </details>
        </div>
      )}

      {mode === 'preset' && (
        <div className="ax-avatar__presets">
          {BOT_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              className={`ax-avatar-preset${presetId === preset.id ? ' is-on' : ''}`}
              onClick={() => applyPreset(preset.id)}
            >
              <AgentAvatar config={preset.config} size={52} paused interactive={false} />
              <span>{preset.name}</span>
            </button>
          ))}
        </div>
      )}

      {mode === 'upload' && (
        <div className="ax-avatar__upload">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => onUpload(e.target.files?.[0])}
          />
          <Button size="sm" onClick={() => fileRef.current?.click()}>
            <Upload size={13} /> Choose image
          </Button>
          {value.avatar_upload && (
            <Button size="sm" variant="ghost" onClick={() => onChange({ avatar_upload: '' })}>
              <X size={13} /> Remove
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
