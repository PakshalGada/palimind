import PageTitle from '../../components/layout/PageTitle';
import ResearchManager from '../../components/ResearchManager';
import '../view.css';

export default function ResearchView() {
  return (
    <main className="view-frame">
      <PageTitle
        eyebrow="Research"
        title="Research"
        subtitle="Persistent projects that accumulate notes, findings, sources and reports."
      />
      <div className="view-frame__body view-frame__body--flush">
        <ResearchManager embedded />
      </div>
    </main>
  );
}
