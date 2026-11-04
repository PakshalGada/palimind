import PageTitle from '../../components/layout/PageTitle';
import ArtifactLibrary from '../../components/ArtifactLibrary';
import { queueArtifactOpen } from '../../components/artifact/pendingOpen';
import { useApp } from '../../AppContext';
import '../view.css';

export default function ArtifactsView() {
  const { setArtifactPanelOpen, setArtifactLibraryOpen } = useApp();

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
            // Library entries are not session artifacts, so they must be
            // handed to the panel whole rather than selected by id.
            queueArtifactOpen(artifact);
            setArtifactLibraryOpen(false);
            setArtifactPanelOpen(true);
          }}
        />
      </div>
    </main>
  );
}
