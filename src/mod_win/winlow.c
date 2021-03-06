/****************************************************************************
 *                                                                          *
 *                            W I N L O W . C                               *
 *                                                                          *
 *                          C Implementation File                           *
 *                                                                          *
 *                      Copyright (C) 2011-2014, AdaCore                    *
 *                                                                          *
 * GNAT is free software;  you can  redistribute it  and/or modify it under *
 * terms of the  GNU General Public License as published  by the Free Soft- *
 * ware  Foundation;  either version 2,  or (at your option) any later ver- *
 * sion.  GNAT is distributed in the hope that it will be useful, but WITH- *
 * OUT ANY WARRANTY;  without even the  implied warranty of MERCHANTABILITY *
 * or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License *
 * for  more details.  You should have  received  a copy of the GNU General *
 * Public License  distributed with GNAT;  see file COPYING.  If not, write *
 * to  the  Free Software Foundation,  51  Franklin  Street,  Fifth  Floor, *
 * Boston, MA 02110-1301, USA.                                              *
 *                                                                          *
 ****************************************************************************/

/* With compiler using mingw64, we cannot include both usual windows includes
 * such as windows.h and the include files coming from the ddk (behavior
 * closer to ms compilers. Not also that we need also to add explicit -I
 * option pointing to the ddk includes.
 *
 * Sourcing basetsd.h ensure _W64 is defined when using mingw64 based
 * compiler. */

#include "basetsd.h"

#ifdef _W64

/* on mingw64, includes are relative to ddk directory. */
#include "ntddk.h"
#include "ntifs.h"
/* not defined in the ddk include files... */
#define MAX_PATH 260
__declspec(dllimport) void WINAPI Sleep(unsigned long dwMilliseconds);

__declspec(dllimport) BOOL WINAPI GetVolumePathNameW(
    LPCWSTR lpszFileName,
    LPWSTR lpszVolumePathName,
    unsigned long cchBufferLength);

#else /* _W64 */

#include "windows.h"
#include "winnt.h"
#include "ntdef.h"
#include "shlobj.h"
#include "stdio.h"

#include "ddk/ntddk.h"
#include "ddk/winddk.h"
#include "ddk/ntifs.h"

#endif /* _W64 */

#include "Python.h"

WCHAR digit_image[] = L"0123456789ABCDEF";
WCHAR trash_dir[] = L"tmp\\trash\\";

UNICODE_STRING Empty_Unicode_String = { Length: 0, MaximumLength: 1, Buffer: L"" };

NTSTATUS NTAPI NtQueryAttributesFile (POBJECT_ATTRIBUTES,
                                        PFILE_BASIC_INFORMATION);

NTSTATUS
move_away(HANDLE h, UNICODE_STRING filename)
{
   IO_STATUS_BLOCK io;
   OBJECT_ATTRIBUTES attr;

   FILE_NAME_INFORMATION query_size;
   FILE_INTERNAL_INFORMATION file_internal_info;

   PFILE_RENAME_INFORMATION rename_information;
   ULONG rename_information_size;

   FILE_DISPOSITION_INFORMATION disp = { TRUE };

   UNICODE_STRING dest;
   WCHAR root_dir[MAX_PATH];
   WCHAR from_buffer[MAX_PATH];
   WCHAR dest_buffer[MAX_PATH];
   NTSTATUS status;
   LONGLONG file_id;
   int i;

   /* Retrieve volume associated with the current path */
   memcpy(from_buffer, filename.Buffer, filename.Length);
   from_buffer[filename.Length] = L'\0';
   /* Note: we ignore the \??\ as only native api understand it */
   GetVolumePathNameW(from_buffer + 4, root_dir, MAX_PATH);

   /* Now compute the destination path */
   dest.Length = 4 * sizeof(WCHAR);
   dest.MaximumLength = sizeof(WCHAR) * MAX_PATH;
   dest.Buffer = dest_buffer;
   memcpy(dest.Buffer, L"\\??\\", 4 * sizeof(WCHAR));
   memcpy(dest.Buffer + dest.Length / sizeof(WCHAR),
          root_dir,
          sizeof(WCHAR) * wcslen(root_dir));
   dest.Length = dest.Length + wcslen(root_dir) * sizeof(WCHAR);

   /* Append to dest our trash directory */
   memcpy(dest.Buffer + dest.Length / sizeof(WCHAR),
          trash_dir, sizeof(trash_dir));

   /* When adjusting dest length ignore the null charater at the end of
      trash_dir. */
   dest.Length += sizeof(trash_dir) - sizeof(WCHAR);

   /* Use the file id which is unique to complete the destination path.  */
   status = NtQueryInformationFile(h, &io, &file_internal_info,
                                   sizeof(file_internal_info),
                                   FileInternalInformation);
   if (!NT_SUCCESS(status)) return status;

   file_id = file_internal_info.IndexNumber.QuadPart;
   for (i=0; i < 16; i++) {
       dest.Buffer[dest.Length / sizeof(WCHAR) + 15 - i] =
          digit_image[file_id & 0xF];
       file_id >>= 4;
   }
   dest.Length += 16 * sizeof(WCHAR);

   /* Not really useful but great if we want to print our buffer using
      printf.  */
   dest.Buffer[dest.Length / sizeof(WCHAR)] = L'\0';

   /* First compute the size of the FILE_RENAME_INFORMATION struct */
   rename_information_size = sizeof(FILE_RENAME_INFORMATION) + dest.Length;
   rename_information = (PFILE_RENAME_INFORMATION) malloc (rename_information_size);
   rename_information->ReplaceIfExists = TRUE;
   rename_information->RootDirectory = NULL;
   rename_information->FileNameLength = dest.Length;
   memcpy(rename_information->FileName, dest.Buffer, dest.Length);

   /* Do the renaming */
   status = NtSetInformationFile(h, &io, rename_information, rename_information_size, FileRenameInformation);
   if (!NT_SUCCESS(status))
   {
      printf ("rename from %ls to %ls failed (%X)\n", filename.Buffer, dest.Buffer, status);
      return status;
   }

   /* Now we should be ready to resume our deletion process */
   return STATUS_SUCCESS;
}
static NTSTATUS
is_dir_empty (HANDLE h)
{
  IO_STATUS_BLOCK io;
  #define FNI FILE_NAMES_INFORMATION

  /* We allocate 3 times the size of the structure in order to fit at least
   * three entries. This way most of the time with one system call we will be
   * able to check if the directory is empty or not. Indeed we expect the
   * function to return at least . and .. entries. */
  const ULONG fni_size = 3 * sizeof (FNI) + 3 * PATH_MAX * sizeof (WCHAR);
  ULONG fni_offset;
  FNI *pfni = (FNI *) malloc (fni_size);
  FNI *fni_cursor;

  NTSTATUS status = NtQueryDirectoryFile (h, NULL, NULL, 0, &io,
                                          pfni,
                                          fni_size,
                                          FileNamesInformation,
                                          FALSE, NULL, TRUE);
  if (status == STATUS_NO_MORE_FILES)
    {
      free(pfni);
      return STATUS_SUCCESS;
    }

  if (!NT_SUCCESS (status))
    {
      /* the system call fails so return an error */
      free(pfni);
      return status;
    }

  /* Skip the first two entries which are .. and . */
  fni_cursor = pfni;
  fni_offset = fni_cursor->NextEntryOffset;
  if (fni_offset == 0)
    {
      free(pfni);
      return STATUS_SUCCESS;
    }
  fni_cursor = (FNI *) ((char *) fni_cursor + fni_offset);
  fni_offset = fni_cursor->NextEntryOffset;
  if (fni_offset == 0)
    {
      free(pfni);
      return STATUS_SUCCESS;
    }
  fni_cursor = (FNI *) ((char *) fni_cursor + fni_offset);

  do
    {
      do
        {
          UNICODE_STRING fname;
          OBJECT_ATTRIBUTES attr;
          FILE_BASIC_INFORMATION fbi;


          fname.Length = fni_cursor->FileNameLength;
          fname.MaximumLength = fname.Length;
          fname.Buffer = fni_cursor->FileName;

          InitializeObjectAttributes (&attr, &fname, 0, h, NULL);
          status = NtQueryAttributesFile (&attr, &fbi);
          if (status != STATUS_DELETE_PENDING
              && status != STATUS_OBJECT_NAME_NOT_FOUND
              && status != STATUS_OBJECT_PATH_NOT_FOUND)
            {
              free (pfni);
              return STATUS_DIRECTORY_NOT_EMPTY;
            }

          fni_offset = fni_cursor->NextEntryOffset;

          if (fni_offset > 0)
            {
              fni_cursor = (FNI *) ((char *) fni_cursor + fni_offset);
            }

        } while (fni_offset != 0);
        status = NtQueryDirectoryFile (h, NULL, NULL, 0, &io, pfni,
                                       fni_size, FileNamesInformation,
                                       FALSE, NULL, FALSE);
        /* we have a new pfni object so reset the cursor to the beginning
         * of the object.  */
        fni_cursor = pfni;
    }
    while (NT_SUCCESS (status));

  free (pfni);
  return STATUS_SUCCESS;
}

typedef struct {
   NTSTATUS last_error_code;
   ULONG    debug;
} UNLINK_RESULT;

UNLINK_RESULT
safe_unlink (UNICODE_STRING name)
{

   UNLINK_RESULT result = { 0, 0 };

   OBJECT_ATTRIBUTES attr;
   FILE_DISPOSITION_INFORMATION disp = { TRUE };
   IO_STATUS_BLOCK io;

   HANDLE handle, handle2;

   FILE_BASIC_INFORMATION file_basic_information;

   BOOLEAN dir_empty = FALSE;
   BOOLEAN try_to_move_away = FALSE;
   BOOLEAN has_been_moved_away = FALSE;
   BOOLEAN is_dir = FALSE;

   BOOLEAN try_again = TRUE;
   ULONG   try_counter = 10;

   NTSTATUS status;

   ULONG share = FILE_SHARE_DELETE;
   ACCESS_MASK access = DELETE;
   ULONG flags = FILE_OPEN_FOR_BACKUP_INTENT;

   /* Initialize the OBJECT_ATTRIBUTES structure needed for most Nt calls.  */
   InitializeObjectAttributes (&attr, &name, OBJ_CASE_INSENSITIVE, NULL, NULL);

   /* Retrieve file attributes */
   status = NtQueryAttributesFile(&attr, &file_basic_information);
   if (!NT_SUCCESS (status)) return (UNLINK_RESULT) { status, 0x1 };

   /* The file is marked read-only, so first try to remove that flag,
      otherwise we will have to move it away in order to remove it, which
      is much slower.  */
   if (FILE_ATTRIBUTE_READONLY & file_basic_information.FileAttributes)
     {
       /* Open the file in write mode */
       status = NtOpenFile(&handle, FILE_WRITE_ATTRIBUTES,
                           &attr, &io, FILE_SHARE_VALID_FLAGS, flags);
       if (NT_SUCCESS (status))
         {
           file_basic_information.FileAttributes = file_basic_information.FileAttributes &
             ~FILE_ATTRIBUTE_READONLY;
           /* Push the updated attributes */
           NTSTATUS status2 = NtSetInformationFile(handle,
                                                   &io, &file_basic_information,
                                                   sizeof(file_basic_information),
                                                   FileBasicInformation);

           NtClose(handle);

           /* Redo the query on the file */
           status = NtQueryAttributesFile(&attr, &file_basic_information);
           if (!NT_SUCCESS (status)) return (UNLINK_RESULT) { status, 0x1 };
          }
     }

   if (FILE_ATTRIBUTE_DIRECTORY & file_basic_information.FileAttributes)
       is_dir = TRUE;
       /* When we trying to delete a directory we might need to list its
          content so ensure that we have the rights to do so.  */
       access = access | FILE_LIST_DIRECTORY | SYNCHRONIZE;
       flags = flags | FILE_SYNCHRONOUS_IO_NONALERT;

   /* First try to open file for deletion */
   while (try_counter > 0)
     {
       status = NtOpenFile (&handle, access, &attr, &io, share, flags);

       if (status == STATUS_SHARING_VIOLATION)
         {
           /* File is already opened for another thing than deletion so try to
              move it somewhere else */
           share = FILE_SHARE_VALID_FLAGS;
           try_to_move_away = TRUE;
           if (try_counter < 2) return (UNLINK_RESULT) { status, 0x4 };
         }
       else
         {
           if (status == STATUS_DELETE_PENDING)
             /* Nothing to do in that case... */
             return (UNLINK_RESULT) { STATUS_SUCCESS, 0x2 };

           if (!NT_SUCCESS (status))
             return (UNLINK_RESULT) { status, 0x3 };
           else
             break;
         }

       Sleep(5L);
       try_counter--;
     }

   /* At this stage we are sure that our file is opened */

   if (try_to_move_away)
     {
       /* Selected method is to move our file away in /tmp/trash */

       /* is the directory empty ? */
       if (is_dir)
         status = is_dir_empty(handle);

       /* We need to move the file away */
       if (NT_SUCCESS(status))
         {
           status = move_away(handle, name);
           if (NT_SUCCESS(status)) has_been_moved_away = TRUE;
         }
     }

   /* At this stage our handle is opened and moved away (if necessary).
      Still we might need in some cases to try several time to delete
      a directory. Note also that we are not using the regular recycle bin
      so we still need to try to delete the file even if it has been moved
      away.  */
   try_counter = 20;
   if (has_been_moved_away)
      /* Our object has been moved away so it won't be a problem in the future
         (like recursive deletion). In that case reduce the number of attempts
         in order to gain performance */
      try_counter = 5;

   if (NT_SUCCESS(status))
      while (try_counter > 0 && try_again)
        {
          status = NtSetInformationFile(handle, &io, &disp,
                                        sizeof(disp),
                                        FileDispositionInformation);

          /* Decide if we need to retry or not ... */
          if (status == STATUS_DIRECTORY_NOT_EMPTY)
             {
               if (!dir_empty) dir_empty = NT_SUCCESS (is_dir_empty(handle));
               /* if there are still objects in the directory just stop */
               if (!dir_empty) try_again = FALSE;
             }
          else if (status == STATUS_CANNOT_DELETE)
             {

               /* If our file has not been moved away move it now */
               if (!try_to_move_away)
                 {
                   status = move_away(handle, name);
                   try_to_move_away = TRUE;
                   if (NT_SUCCESS(status)) has_been_moved_away = TRUE;
                 }

               /* Duplicate our handle and try set delete_on_close */
               InitializeObjectAttributes(&attr, &Empty_Unicode_String,
                                          OBJ_CASE_INSENSITIVE, handle, NULL);
               status = NtOpenFile(&handle2, access, &attr, &io,
                                   share,
                                   flags | FILE_DELETE_ON_CLOSE);
               if (NT_SUCCESS (status))
                 NtClose(handle2);

             }
          else
             if (!NT_SUCCESS (status)) try_again = FALSE;

          /* Should we loop again ? */
          if (!NT_SUCCESS (status) && try_again)
             {
               Sleep(5L);
               try_counter--;
             }
          else
             try_again = FALSE;
        }

   NtClose(handle);
   if (has_been_moved_away && !NT_SUCCESS(status))
      return (UNLINK_RESULT) { STATUS_SUCCESS, 0x6 };

   return (UNLINK_RESULT) {status, 0};
}

static PyObject
*py_safe_unlink(PyObject *self, PyObject *args)
{
   /* Initialize the UNICODE string that contains the file name using native
      representation.  */
   UNICODE_STRING name;
   UNLINK_RESULT  result;
   name.Length = PyUnicode_GetSize (PyTuple_GetItem(args, 0)) * sizeof(WCHAR);
   name.MaximumLength = name.Length;
   name.Buffer = PyUnicode_AsUnicode (PyTuple_GetItem(args, 0));

   result = safe_unlink(name);
   if (NT_SUCCESS(result.last_error_code))
      return PyInt_FromLong(0);

   printf("safe_unlink failed %d, %d\n", result.last_error_code, result.debug);
   return PyInt_FromLong(result.last_error_code);
}

static PyMethodDef WinLowMethods[] =
{
  {"safe_unlink", py_safe_unlink, METH_VARARGS, "remove a file or a directory"},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC
init_winlow(void)
{
  PyObject *m;
  m = Py_InitModule("_winlow", WinLowMethods);
}
