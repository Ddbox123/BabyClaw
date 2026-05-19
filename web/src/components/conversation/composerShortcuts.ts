export type ComposerKeydownInput = {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  isComposing: boolean;
};

export function shouldSubmitComposerOnKeydown(input: ComposerKeydownInput) {
  if (input.isComposing) {
    return false;
  }
  if (input.key !== "Enter") {
    return false;
  }
  if (input.shiftKey || input.ctrlKey || input.metaKey || input.altKey) {
    return false;
  }
  return true;
}
