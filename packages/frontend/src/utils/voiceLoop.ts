export function shouldAutoSendVoice(transcript: string, voiceMode: boolean): boolean {
  return Boolean(voiceMode && transcript.trim());
}

export function shouldRestartVoice({
  voiceMode,
  wasGenerating,
  isGenerating,
  isRecording,
  isTranscribing,
}: {
  voiceMode: boolean;
  wasGenerating: boolean;
  isGenerating: boolean;
  isRecording: boolean;
  isTranscribing: boolean;
}): boolean {
  return voiceMode && wasGenerating && !isGenerating && !isRecording && !isTranscribing;
}
