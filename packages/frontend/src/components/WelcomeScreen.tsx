import { useMemo } from 'react';
import { FolderPlus, Sparkles } from 'lucide-react';
import { Button, EmptyState } from '../ui/primitives';
import { useUserName } from '../hooks/useUserName';
import { getGreeting } from '../utils/greeting';
import OnboardingChecklist from './onboarding/OnboardingChecklist';

export default function WelcomeScreen() {
  const name = useUserName();
  const greeting = useMemo(() => getGreeting(name), [name]);

  const openPicker = () => {
    window.dispatchEvent(new CustomEvent('palimind:open-dir-picker'));
  };

  return (
    <main className="chat-area" id="main-area">
      <div id="welcome-screen" className="welcome-screen">
        <EmptyState
          className="welcome-empty"
          icon={
            <span className="welcome-badge">
              <Sparkles size={14} />
              Local-First Intelligence OS
            </span>
          }
          title={greeting}
          description="Index documents, chat with local LLMs, and explore knowledge graphs — 100% offline and private."
          action={
            <Button variant="primary" size="md" className="welcome-cta" onClick={openPicker}>
              <FolderPlus size={17} />
              Select Workspace Directory
            </Button>
          }
        >
          {/* Guided first-run flow replaces the static feature cards: every
              card below used to trigger the same directory picker anyway. */}
          <div className="onboarding-wrap">
            <OnboardingChecklist />
          </div>
        </EmptyState>
      </div>
    </main>
  );
}
