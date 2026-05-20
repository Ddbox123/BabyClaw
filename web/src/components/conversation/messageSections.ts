import { ConversationMessage, MentalStateSnapshot } from "../../api/types";

export function hasMentalSnapshot(snapshot: MentalStateSnapshot | undefined) {
  if (!snapshot) {
    return false;
  }
  return [
    snapshot.mood,
    snapshot.feeling,
    snapshot.whisper,
    snapshot.cognitiveState,
  ].some((value) => String(value ?? "").trim().length > 0);
}

export function hasThoughtBlock(message: ConversationMessage) {
  return message.role === "assistant"
    && Boolean(message.thought?.trim());
}

export function hasMentalBlock(message: ConversationMessage) {
  return message.role === "assistant" && hasMentalSnapshot(message.mentalSnapshot);
}

export function hasToolBlock(message: ConversationMessage) {
  return message.role === "assistant" && (message.toolCalls?.length ?? 0) > 0;
}

export function hasUserContent(message: ConversationMessage) {
  return message.role !== "assistant" && Boolean(message.content.trim());
}

export function hasResponseBlock(message: ConversationMessage) {
  return message.role === "assistant" && Boolean(message.content.trim());
}
