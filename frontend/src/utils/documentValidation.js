const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf']
const IMAGE_ONLY_TYPES = ['image/jpeg', 'image/jpg', 'image/png']
const MAX_SIZE_MB = 5

// Shared between UploadCard (single-upload drop zone) and UploadPage's
// bulk-upload flow, so both enforce the exact same type/size rules the
// backend does, without duplicating them.
export function validateDocumentFile(file, { imageOnly = false } = {}) {
  const acceptedTypes = imageOnly ? IMAGE_ONLY_TYPES : ACCEPTED_TYPES
  if (!acceptedTypes.includes(file.type)) {
    return imageOnly ? 'Only JPG, JPEG, and PNG files are allowed.' : 'Only JPG, JPEG, PNG, and PDF files are allowed.'
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    return `File size must be ${MAX_SIZE_MB} MB or less.`
  }
  return null
}
