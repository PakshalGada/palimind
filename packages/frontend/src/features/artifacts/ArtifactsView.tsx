import { useState } from 'react';
import PageTitle from '../../components/layout/PageTitle';
import ArtifactLibrary, { type OpenedArtifact } from '../../components/ArtifactLibrary';
import { useApp } from '../../AppContext';
import '../view.css';

export default function ArtifactsView() {
  const { openArtifact } = useApp();
  const [, setOpened] = useState<OpenedArtifact | null>(null);

  return (
    <main className="view-frame">
      <PageTitle
        eyebrow="Library"
        title="Artifacts"
        subtitle="Everything you have saved: documents, code, slides and visual pieces."
      />
      <div className="view-frame__body view-frame__body--flush">
        <ArtifactLibrary
          embedded
          open
          onClose={() => undefined}
          onOpen={(artifact) => {
            setOpened(artifact);
            openArtifact(artifact.id);
          }}
        />
      </div>
    </main>
  );
}
