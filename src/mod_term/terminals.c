/****************************************************************************
 *                                                                          *
 *                            T E R M I N A L S                             *
 *                                                                          *
 *                          C Implementation File                           *
 *                                                                          *
 *                      Copyright (C) 2008-2014, AdaCore                    *
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
 * As a  special  exception,  if you  link  this file  with other  files to *
 * produce an executable,  this file does not by itself cause the resulting *
 * executable to be covered by the GNU General Public License. This except- *
 * ion does not  however invalidate  any other reasons  why the  executable *
 * file might be covered by the  GNU Public License.                        *
 *                                                                          *
 * GNAT was originally developed  by the GNAT team at  New York University. *
 * Extensive contributions were provided by Ada Core Technologies Inc.      *
 *                                                                          *
 ****************************************************************************/

#ifndef WIN32

/* First defined some macro to identify easily some systems */
#if defined (__FreeBSD__) \
 || defined (__OpenBSD__) \
 || defined (__NetBSD__) \
 || defined (__DragonFly__)
#   define FREEBSD
#endif
#if defined (__alpha__) && defined (__osf__)
#   define OSF1
#endif
#if defined (__mips) && defined (__sgi)
#   define IRIX
#endif

/* Include every system header we need */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

/* On some system termio is either absent or including it will disable termios
   (HP-UX).  */
#if ! defined (__hpux__) && ! defined (FREEBSD) && ! defined (__APPLE__)
#   include <termio.h>
#endif

#include <sys/ioctl.h>
#include <termios.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#if defined (sun)
#   include <sys/stropts.h>
#endif
#if defined (FREEBSD) || defined (sun)
#   include <sys/signal.h>
#endif
#if defined (__hpux__)
#   include <sys/termio.h>
#   include <sys/stropts.h>
#endif

#define CDISABLE _POSIX_VDISABLE

/* On HP-UX and Sun system, there is a bzero function but with a different
   signature. Use memset instead */
#if defined (__hpux__) || defined (sun) || defined (_AIX)
#   define bzero(s,n) memset (s,0,n)
#endif

/* POSIX does not specify how to open the master side of a terminal.
   Several methods are available (system specific):
      1- using a cloning device (USE_CLONE_DEVICE)
      2- getpt                  (USE_GETPT)
      3- openpty                (USE_OPENPTY)
      4- _getpty                (USE_GETPTY)

   When using the cloning device method, the macro USE_CLONE_DEVICE should
   contains a full path to the adequate device.

   When a new system is about to be supported, one of the following macros
   should be set. Otherwise, allocate_pty_desc will return an error.  */

/* Configurable part */
#if defined (__APPLE__) || defined (FREEBSD)
#define USE_OPENPTY
#elif defined (IRIX)
#define USE_GETPTY
#elif defined (linux)
#define USE_GETPT
#elif defined (sun)
#define USE_CLONE_DEVICE "/dev/ptmx"
#elif defined (_AIX)
#define USE_CLONE_DEVICE "/dev/ptc"
#elif defined (OSF1)
/* On Tru64, the systems offers various interfaces to open a terminal:
    - /dev/ptmx: this the system V driver (stream based);
    - /dev/ptmx_bsd: the non stream based clone device;
    - the openpty function which use BSD interface.

   Using directly /dev/ptmx_bsd on Tru64 5.1B seems to consume all
   the available slave ptys (why ?). When using openpty it seems that
   the function handles the creation of entries in /dev/pts when
   necessary and so avoids this starvation issue. The pty man entry
   also suggests the use openpty.  */
#define USE_OPENPTY
#elif defined (__hpux__)
/* On HP-UX we use the streamed version. Using the non-streamed version is not
   recommanded (through "/dev/ptym/clone"). Indeed it seems that there are
   issues to detect process termination.  */
#define USE_CLONE_DEVICE "/dev/ptmx"
#endif

/* structure that holds information about the terminal used and the process
   connected on the slave side.  */
typedef struct pty_desc_struct
{
   int  master_fd;     /* fd of the master side if the terminal */
   int  slave_fd;      /* fd of the slave side */
   char slave_name[32];   /* filename of the slave side */
   int  child_pid;     /* PID of the child process connected to the slave side
                         of the terminal */
} term_handler;

/* allocate_pty_desc - allocate a pseudo terminal

   PARAMETERS
     out desc  returned pointer to a term_handler structure containing
               information about the opened pseudo terminal
   RETURNS
     -1        if failed
      0        if ok

   COMMENTS
     If the function is successful we should have at least the master side fd
     and the slave side filename. On some systems, the slave side will also be
     opened. If this is not the case, the slave side will be open once we are
     in the child process (note that opening the slave side at this stage will
     failed...).  */

extern char* ptsname (int);

static int
allocate_pty_desc (term_handler **desc)
{
  term_handler *result;
  int  status      =  0;
  int  slave_fd    = -1;
  int  master_fd   = -1;
  char *slave_name = NULL;

#ifdef USE_GETPT
  master_fd = getpt ();
#elif defined (USE_OPENPTY)
  status = openpty (&master_fd, &slave_fd, NULL, NULL, NULL);
#elif defined (USE_GETPTY)
  slave_name = _getpty (&master_fd, O_RDWR | O_NDELAY, 0600, 0);
  if (slave_name == NULL)
    status = -1;
#elif defined (USE_CLONE_DEVICE)
  master_fd = open (USE_CLONE_DEVICE, O_RDWR | O_NONBLOCK, 0);
#else
  printf ("[error]: terminal support is not configured\n");
  return -1;
#endif

  /* At this stage, we should have the master side fd, and status
     should be 0.  */
  if (status != 0 || master_fd < 0)
    {
      /* If this is not the case, close all opened files and return -1.  */
      printf ("[error]: cannot allocate master side of the pty\n");
      if (master_fd >= 0) close (master_fd);
      if (slave_fd  >= 0) close (slave_fd);
      *desc = NULL;
      return -1;
    }

  /* If necessary, retrieve the file name of the slave side.  */
  if (slave_name == NULL) slave_name = (char *) ptsname (master_fd);

  /* Now we should have the slave file name.  */
  if (slave_name == NULL)
    {
      /* If not the case close any opened file and return -1.  */
      printf ("[error]: cannot allocate slave side of the pty\n");
      if (master_fd >= 0) close (master_fd);
      if (slave_fd  >= 0) close (slave_fd);
      *desc = NULL;
      return -1;
    }

  /* Grant access to the slave side.  */
  grantpt (master_fd);
  /* Unlock the terminal.  */
  unlockpt (master_fd);

  /* Set desc and return 0.  */
  result = malloc (sizeof (term_handler));
  result->master_fd  = master_fd;
  result->slave_fd   = slave_fd;
  /* The string returned by ptsname or _getpty is a statically-allocated
     string.  So we should make a copy.  */
  strncpy (result->slave_name, slave_name, sizeof (result->slave_name));
  result->slave_name[sizeof (result->slave_name) - 1] = '\0';
  result->child_pid  = -1;
  *desc=result;
  return 0;
}

/* Some utility macros that make the code of child_setup_tty easier
   to read.  */
#define __enable(a, b) ((a) |= (b))
#define __disable(a, b) ((a) &= ~(b))

/* Some properties do not exist on all systems. Set their value to 0 in that
   case.  */
#ifndef IUCLC
#define IUCLC 0
#endif
#ifndef OLCUC
#define OLCUC 0
#endif
#ifndef NLDLY
#define NLDLY 0
#endif
#ifndef CRDLY
#define CRDLY 0
#endif
#ifndef TABDLY
#define TABDLY 0
#endif
#ifndef BSDLY
#define BSDLY 0
#endif
#ifndef VTDLY
#define VTDLY 0
#endif
#ifndef FFDLY
#define FFDLY 0
#endif

/* child_setup_tty - set terminal properties

   PARAMETERS
     file descriptor of the slave side of the terminal

   RETURNS
     0 if success, any other value if failed.

   COMMENTS
     None */

static int
child_setup_tty (int fd)
{
  struct termios s;
  int    status;

  /* ensure that s is filled with 0 */
  bzero (&s, sizeof (&s));

  /* Get the current terminal settings */
  status = tcgetattr (fd, &s);
  if (status != 0)
    return -1;

  /* Adjust input modes.  */
  __disable (s.c_iflag, IUCLC);    /* don't transform to lower case */
  __disable (s.c_iflag, ISTRIP);   /* don't delete 8th bit */

  /* Adjust output modes.  */
  __enable  (s.c_oflag, OPOST);    /* enable postprocessing */
  __disable (s.c_oflag, ONLCR);    /* don't map LF to CR-LF */
  __disable (s.c_oflag, NLDLY|CRDLY|TABDLY|BSDLY|VTDLY|FFDLY);
                                   /* disable delays */
  __disable (s.c_oflag, OLCUC);    /* don't transform to upper case */

  /* Adjust control modes.  */
  s.c_cflag = (s.c_cflag & ~CSIZE) | CS8; /* Don't strip 8th bit */

  /* Adjust local modes.  */
  __disable (s.c_lflag, ECHO);     /* disable echo */
  __enable  (s.c_lflag, ISIG);     /* enable signals */
  __enable  (s.c_lflag, ICANON);   /* erase/kill/eof processing */

  /* Adjust control characters.  */
  /* IMPORTANT: we need to ensure that Ctrl-C will trigger an interrupt signal
     otherwise send_signal_via_characters will fail */
  s.c_cc[VEOF]   = 04;         /* insure that EOF is Control-D */
  s.c_cc[VERASE] = CDISABLE;   /* disable erase processing */
  s.c_cc[VKILL]  = CDISABLE;   /* disable kill processing */
  s.c_cc[VQUIT]  = 28;         /* Control-\ */
  s.c_cc[VINTR]  = 03;         /* Control-C */
  s.c_cc[VEOL]   = CDISABLE;
  s.c_cc[VSUSP]  = 26;         /* Control-Z */

  /* Push our changes.  */
  status = tcsetattr (fd, TCSADRAIN, &s);
  return status;
}

/* setup_communication - interface to the external world.

   Should be called before forking. On Unixes this function only call
   allocate_pty_desc.  The Windows implementation (in different part of
   this file) is very different.

   PARAMETERS
    out desc   returned pointer to a term_handler structure

   RETURNS
    0 if success, -1 otherwise.  */

int gvd_setup_communication (term_handler** desc)
{
  int status;

  return allocate_pty_desc (desc);
}

/* gvd_setup_parent_communication - interface to the external world.

   Should be called after forking in the parent process

   PARAMETERS
     out in_fd
     out out_fd
     out err_fd fds corresponding to the parent side of the
                terminal
     in pid_out child process pid
   RETURNS
    0.  */
int
gvd_setup_parent_communication
  (term_handler *desc,
   int*     in_fd,  /* input */
   int*     out_fd, /* output */
   int*     err_fd, /* error */
   int*     pid_out)
{

  *in_fd = desc->master_fd;
  *out_fd= desc->master_fd;
  *err_fd= desc->master_fd;
  desc->child_pid = *pid_out;
  /* On some systems such as MAC OS or FreeBSD we open both slave and
     master at the same time. slave side is only used by the child process.
     Ensure we do not keep it open after forking otherwise we may leak
     file descriptors.  */
  if (desc->slave_fd >= 0)
    {
      close(desc->slave_fd);
      desc->slave_fd = -1;
    }
  return 0;
}

/* gvd_setup_winsize - Sets up the size of the terminal
   This lets the process know the size of the terminal.  */

void
gvd_setup_winsize (term_handler *desc, int rows, int columns)
{
#ifdef TIOCGWINSZ
  struct winsize s;
  s.ws_row = (unsigned short)rows;
  s.ws_col = (unsigned short)columns;
  s.ws_xpixel = 0;
  s.ws_ypixel = 0;
  ioctl (desc->master_fd, TIOCSWINSZ, &s);
#ifdef SIGWINCH
  if (desc->child_pid > 0) {
     /* Let the process know about the change in size.  */
     kill (desc->child_pid, SIGWINCH);
  }
#endif
#endif
}

/* gvd_setup_child_communication - interface to external world.

   Should be called after forking in the child process. On Unixes,
   this function first adjust the line setting, set standard output,
   input and error and then spawn the program.

   PARAMETERS
     desc      a term_handler structure containing the pty parameters
     new_argv  argv of the program to be spawned

   RETURNS
     This function should not return.  */

int
gvd_setup_child_communication (term_handler *desc, char **new_argv) {
  int status;
  int pid = getpid ();

  setsid ();

  /* Open the slave side of the terminal, if not already done earlier.  */
  if (desc->slave_fd == -1)
#if defined (_AIX)
    /* On AIX, if the slave process is not opened with O_NDELAY or O_NONBLOCK
       then we might have some processes hanging on I/O system calls. Not sure
       we can do that for all platforms so do it only on AIX for the moment.
       On AIX O_NONBLOCK and O_NDELAY have slightly different meanings. When
       reading on the slave fd, in case there is no data available, if O_NDELAY
       is set then 0 is returned. If O_NON_BLOCK is -1 is returned. It seems
       that interactive programs such as GDB prefer the O_NDELAY behavior.
       We chose O_NONBLOCK because it allows us to make the distinction
       between a true EOF and an EOF returned because there is no data
       available to be read.  */
    desc->slave_fd = open (desc->slave_name, O_RDWR | O_NONBLOCK, 0);
#else
    desc->slave_fd = open (desc->slave_name, O_RDWR, 0);
#endif

#if defined (sun) || defined (__hpux__)
  /* On systems such as Solaris we are using stream. We need to push the right
     "modules" in order to get the expected terminal behaviors. Otherwise
     functionalities such as termios are not available.  */
  ioctl (desc->slave_fd, I_PUSH, "ptem");
  ioctl (desc->slave_fd, I_PUSH, "ldterm");
  ioctl (desc->slave_fd, I_PUSH, "ttcompat");
#endif

#ifdef TIOCSCTTY
  /* Make the tty the controlling terminal.  */
  status = ioctl (desc->slave_fd, TIOCSCTTY, 0);
#endif

  /* Adjust tty settings.  */
  child_setup_tty (desc->slave_fd);
  gvd_setup_winsize (desc, 24, 80); /* To prevent errors in some shells.  */

  /* stdin, stdout and stderr should now be our tty.  */
  dup2 (desc->slave_fd, 0);
  dup2 (desc->slave_fd, 1);
  dup2 (desc->slave_fd, 2);
  if (desc->slave_fd > 2)
    close (desc->slave_fd);

  /* Adjust process group settings.  */
  status = setpgid (pid, pid);
  status = tcsetpgrp (0, pid);

  /* Launch the program.  */
  status = execvp (new_argv[0], new_argv);
  printf ("status: %d\n", status);

  /* Return the pid.  */
  return pid;
}

/* send_signal_via_characters

   Send a characters that will trigger a signal in the child process.

   PARAMETERS
    desc  A term_handler structure containing terminal information
    int   A signal number

   RETURNS
    None.  */

static void
send_signal_via_characters (term_handler *desc, int signal_number)
{
  char ctrl_c         = 03;
  char ctrl_backslash = 28;
  char ctrl_Z         = 26;

  switch (signal_number)
    {
      case SIGINT:
	write (desc->master_fd, &ctrl_c, 1); return;
      case SIGQUIT:
	write (desc->master_fd, &ctrl_backslash, 1); return;
      case SIGTSTP:
	write (desc->master_fd, &ctrl_Z, 1); return;
    }
}

/* gvd_interrupt_process - interrupt the child process

   PARAMETERS
     desc a term_handler structure.  */

int
gvd_interrupt_process (term_handler *desc)
{
  send_signal_via_characters (desc, SIGINT);
  return 0;
}

/* gvd_interrupt_pid - interrupt a process group

   PARAMETERS
     pid  pid of the process to interrupt.  */

int
gvd_interrupt_pid (int pid)
{
  kill (-pid, SIGINT);
  return 0;
}

/* gvd_terminate_process - kill a child process

   PARAMETERS
     desc term_handler structure.  */

int
gvd_terminate_process (term_handler *desc)
{
  close(desc->master_fd);
  return kill (desc->child_pid, SIGKILL);
}

/* gvd_waitpid - wait for the child process to die

   PARAMETERS
     desc term_handler structure

   RETURNS
     exit status of the child process.  */

int
gvd_waitpid (term_handler *desc)
{
  int status = 0;

  waitpid (desc->child_pid, &status, 0);
  return WEXITSTATUS (status);
}

/* gvd_tty_supported - Are tty supported ?

   RETURNS
     always 1 on Unix systems.  */

int
gvd_tty_supported (void)
{
  return 1;
}

/* gvd_free_process - Free a term_handler structure

   PARAMETERS
     in out desc: a pty desc structure.  */

void
gvd_free_process (void* desc)
{
  free ((term_handler *)desc);
}

/* gvd_send_header - Dummy function.

   This interface is only used on Windows.  */

void
gvd_send_header (term_handler* desc, char header[5], int size, int *ret)
{
  *ret = 0;
}

/* gvd_reset_tty - Reset line setting

   PARAMETERS
     desc: a term_handler structure.  */

void
gvd_reset_tty (term_handler* desc)
{
  child_setup_tty (desc->master_fd);
}

/* gvd_new_tty - allocate a new terminal

   RETURNS
     a term_handler structure.  */

term_handler *
gvd_new_tty (void)
{
  int status;
  term_handler* desc;
  status = allocate_pty_desc (&desc);
  child_setup_tty (desc->master_fd);
  return desc;
}

/* gvd_close_tty - close a terminal

   PARAMETERS
     desc  a term_handler strucure.  */

void
gvd_close_tty (term_handler* desc)
{
  if (desc->master_fd >= 0) close (desc->master_fd);
  if (desc->slave_fd  >= 0) close (desc->slave_fd);
}

/* gvd_tty_name - return slave side device name

   PARAMETERS
     desc  a term_handler strucure

   RETURNS
     a string.  */

char *
gvd_tty_name (term_handler* desc)
{
  return desc->slave_name;
}

/* gvd_tty_name - return master side fd

   PARAMETERS
     desc  a term_handler strucure
   RETURNS
     a fd.  */

int
gvd_tty_fd (term_handler* desc)
{
  return desc->master_fd;
}

#ifdef __hpux__
#include <sys/ptyio.h>
#endif

#include <sys/time.h>

#ifndef NO_FD_SET
#define SELECT_MASK fd_set
#else /* !NO_FD_SET */
#ifndef _AIX
typedef long fd_mask;
#endif /* _AIX */
#ifdef _IBMR2
#define SELECT_MASK void
#else /* !_IBMR2 */
#define SELECT_MASK int
#endif /* !_IBMR2 */
#endif /* !NO_FD_SET */

int
__gnat_expect_poll (int *fd, int num_fd, int timeout, int *is_set)
{
  struct timeval tv;
  SELECT_MASK rset;
  SELECT_MASK eset;

  int max_fd = 0;
  int ready;
  int i;
  int received;

  tv.tv_sec  = timeout / 1000;
  tv.tv_usec = (timeout % 1000) * 1000;

  do
    {
      FD_ZERO (&rset);
      FD_ZERO (&eset);

      for (i = 0; i < num_fd; i++)
	{
	  FD_SET (fd[i], &rset);
	  FD_SET (fd[i], &eset);

	  if (fd[i] > max_fd)
	    max_fd = fd[i];
	}

      ready =
	select (max_fd + 1, &rset, NULL, &eset, timeout == -1 ? NULL : &tv);

      if (ready > 0)
	{
	  received = 0;

	  for (i = 0; i < num_fd; i++)
	    {
	      if (FD_ISSET (fd[i], &rset))
		{
		  is_set[i] = 1;
		  received = 1;
		}
	      else
		is_set[i] = 0;
	    }

#ifdef __hpux__
	  for (i = 0; i < num_fd; i++)
	    {
	      if (FD_ISSET (fd[i], &eset))
		{
		  struct request_info ei;

		  /* Only query and reset error state if no file descriptor
		     is ready to be read, otherwise we will be signalling a
		     died process too early.  */

		  if (!received)
		    {
		      ioctl (fd[i], TIOCREQCHECK, &ei);

		      if (ei.request == TIOCCLOSE)
			{
			  ioctl (fd[i], TIOCREQSET, &ei);
			  return -1;
			}

		      ioctl (fd[i], TIOCREQSET, &ei);
		    }
		  ready--;
		}
	    }
#endif
	}
    } while (timeout == -1 && ready == 0);

  return ready;
}

#else /* WIN32 */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#include <windows.h>
#include <process.h>
#include <signal.h>
#include <io.h>
#define MAXPATHLEN 1024

#define Qnil 0
#define report_file_error(x, y) fprintf (stderr, "Error: %s\n", x);

typedef struct GVD_Process {
  int pid;           /* Number of this process */
  PROCESS_INFORMATION procinfo;
  HANDLE w_infd, w_outfd;
  HANDLE w_forkin, w_forkout;
  int infd, outfd;
} term_handler;

static DWORD AbsoluteSeek(HANDLE, DWORD);
static VOID  ReadBytes(HANDLE, LPVOID, DWORD);

#define XFER_BUFFER_SIZE 2048

/* This tell if the executable we're about to launch uses a GUI interface. */
/* if we can't determine it, we will return true */
static int
is_gui_app (char *exe)
{
  HANDLE hImage;

  DWORD  bytes;
  DWORD  iSection;
  DWORD  SectionOffset;
  DWORD  CoffHeaderOffset;
  DWORD  MoreDosHeader[16];
  CHAR   *file;
  size_t nlen;

  ULONG  ntSignature;

  IMAGE_DOS_HEADER      image_dos_header;
  IMAGE_FILE_HEADER     image_file_header;
  IMAGE_OPTIONAL_HEADER image_optional_header;
  IMAGE_SECTION_HEADER  image_section_header;

  /*
   *  Open the reference file.
  */
  nlen = strlen (exe);
  file = exe;
  if (nlen > 2) {
    if (exe[0] == '"') {
      /* remove quotes */
      nlen -= 2;
      file = malloc ((nlen + 1) * sizeof (char));
      memcpy (file, &exe[1], nlen);
      file [nlen] = '\0';
    }
  }
  hImage = CreateFile(file,
                      GENERIC_READ,
                      FILE_SHARE_READ,
                      NULL,
                      OPEN_EXISTING,
                      FILE_ATTRIBUTE_NORMAL,
                      NULL);

  if (file != exe) {
    free (file);
  }

  if (INVALID_HANDLE_VALUE == hImage)
    {
      report_file_error ("Could not open exe: ", Qnil);
      report_file_error (exe, Qnil);
      report_file_error ("\n", Qnil);
      CloseHandle (hImage);
      return -1;
    }

  /*
   *  Read the MS-DOS image header.
   */
  ReadBytes(hImage, &image_dos_header, sizeof(IMAGE_DOS_HEADER));

  if (IMAGE_DOS_SIGNATURE != image_dos_header.e_magic)
    {
      report_file_error("Sorry, I do not understand this file.\n", Qnil);
      CloseHandle (hImage);
      return -1;
    }

  /*
   *  Read more MS-DOS header.       */
  ReadBytes(hImage, MoreDosHeader, sizeof(MoreDosHeader));
   /*
   *  Get actual COFF header.
   */
  CoffHeaderOffset = AbsoluteSeek(hImage, image_dos_header.e_lfanew) +
                     sizeof(ULONG);
  if (CoffHeaderOffset < 0) {
    CloseHandle (hImage);
    return -1;
  }

  ReadBytes (hImage, &ntSignature, sizeof(ULONG));

  if (IMAGE_NT_SIGNATURE != ntSignature)
    {
      report_file_error ("Missing NT signature. Unknown file type.\n", Qnil);
      CloseHandle (hImage);
      return -1;
    }

  SectionOffset = CoffHeaderOffset + IMAGE_SIZEOF_FILE_HEADER +
    IMAGE_SIZEOF_NT_OPTIONAL_HEADER;

  ReadBytes(hImage, &image_file_header, IMAGE_SIZEOF_FILE_HEADER);

  /*
   *  Read optional header.
   */
  ReadBytes(hImage,
            &image_optional_header,
            IMAGE_SIZEOF_NT_OPTIONAL_HEADER);

  CloseHandle (hImage);

  switch (image_optional_header.Subsystem)
    {
    case IMAGE_SUBSYSTEM_UNKNOWN:
        return 1;
        break;

    case IMAGE_SUBSYSTEM_NATIVE:
        return 1;
        break;

    case IMAGE_SUBSYSTEM_WINDOWS_GUI:
        return 1;
        break;

    case IMAGE_SUBSYSTEM_WINDOWS_CUI:
        return 0;
        break;

    case IMAGE_SUBSYSTEM_OS2_CUI:
        return 0;
        break;

    case IMAGE_SUBSYSTEM_POSIX_CUI:
        return 0;
        break;

    default:
        /* Unknown, return GUI app to be preservative: if yes, it will be
           correctly launched, if no, it will be launched, and a console will
           be also displayed, which is not a big deal */
        return 1;
        break;
    }

}

static DWORD
AbsoluteSeek (HANDLE hFile, DWORD offset)
{
    DWORD newOffset;

    newOffset = SetFilePointer (hFile, offset, NULL, FILE_BEGIN);

    if (newOffset == 0xFFFFFFFF)
      return -1;
    else
      return newOffset;
}

static VOID
ReadBytes (HANDLE hFile, LPVOID buffer, DWORD size)
{
  DWORD bytes;

  if (!ReadFile(hFile, buffer, size, &bytes, NULL))
    {
      size = 0;
      return;
    }
  else if (size != bytes)
    {
      return;
    }
}

static int
nt_spawnve (char *exe, char **argv, char *env, term_handler *process)
{
  STARTUPINFO start;
  SECURITY_ATTRIBUTES sec_attrs;
  SECURITY_DESCRIPTOR sec_desc;
  DWORD flags;
  char dir[ MAXPATHLEN ];
  int pid;
  int is_gui, use_cmd;
  char *cmdline, *parg, **targ;
  int arglen;

  /* The escape character to be used when quoting arguments.  */
  const char escape_char = '\\';

  /* we have to do some conjuring here to put argv and envp into the
     form CreateProcess wants...  argv needs to be a space separated/null
     terminated list of parameters, and envp is a null
     separated/double-null terminated list of parameters.

     Additionally, zero-length args and args containing whitespace or
     quote chars need to be wrapped in double quotes - for this to work,
     embedded quotes need to be escaped as well.  The aim is to ensure
     the child process reconstructs the argv array we start with
     exactly, so we treat quotes at the beginning and end of arguments
     as embedded quotes.

     Note that using backslash to escape embedded quotes requires
     additional special handling if an embedded quote is already
     preceded by backslash, or if an arg requiring quoting ends with
     backslash.  In such cases, the run of escape characters needs to be
     doubled.  For consistency, we apply this special handling as long
     as the escape character is not quote.

     Since we have no idea how large argv and envp are likely to be we
     figure out list lengths on the fly and allocate them.  */

  /* do argv...  */
  arglen = 0;
  targ = argv;
  while (*targ)
    {
      char *p = *targ;
      int need_quotes = 0;
      int escape_char_run = 0;

      if (*p == 0)
	need_quotes = 1;
      for ( ; *p; p++)
	{
	  if (*p == '"')
	    {
	      /* allow for embedded quotes to be escaped */
	      arglen++;
	      need_quotes = 1;
	      /* handle the case where the embedded quote is already escaped */
	      if (escape_char_run > 0)
		{
		  /* To preserve the arg exactly, we need to double the
		     preceding escape characters (plus adding one to
		     escape the quote character itself).  */
		  arglen += escape_char_run;
		}
	    }
	  else if (*p == ' ' || *p == '\t')
	    {
	      need_quotes = 1;
	    }

	  if (*p == escape_char && escape_char != '"')
	    escape_char_run++;
	  else
	    escape_char_run = 0;
	}
      if (need_quotes)
	{
	  arglen += 2;
	  /* handle the case where the arg ends with an escape char - we
	     must not let the enclosing quote be escaped.  */
	  if (escape_char_run > 0)
	    arglen += escape_char_run;
	}
      arglen += strlen (*targ) + 1;
      targ++;
    }

  is_gui = is_gui_app (argv[0]);
  use_cmd = FALSE;

  if (is_gui == -1) {
    /* could not determine application type. Try launching with "cmd /c" */
    is_gui = FALSE;
    arglen += 7;
    use_cmd = TRUE;
  }

  cmdline = (char*)malloc (arglen + 1);
  targ = argv;
  parg = cmdline;

  if (use_cmd == TRUE) {
    strcpy (parg, "cmd /c ");
    parg += 7;
  }

  while (*targ)
    {
      char * p = *targ;
      int need_quotes = 0;

      if (*p == 0)
	need_quotes = 1;

      for ( ; *p; p++)
	if (*p == ' ' || *p == '\t' || *p == '"')
	  need_quotes = 1;

      if (need_quotes)
	{
	  int escape_char_run = 0;
	  char * first;
	  char * last;

	  p = *targ;
	  first = p;
	  last = p + strlen (p) - 1;
	  *parg++ = '"';
	  for ( ; *p; p++)
	    {
	      if (*p == '"')
		{
		  /* double preceding escape chars if any */
		  while (escape_char_run > 0)
		    {
		      *parg++ = escape_char;
		      escape_char_run--;
		    }
		  /* escape all quote chars, even at beginning or end */
		  *parg++ = escape_char;
		}
	      *parg++ = *p;

	      if (*p == escape_char && escape_char != '"')
		escape_char_run++;
	      else
		escape_char_run = 0;
	    }
	  /* double escape chars before enclosing quote */
	  while (escape_char_run > 0)
	    {
	      *parg++ = escape_char;
	      escape_char_run--;
	    }
	  *parg++ = '"';
	}
      else
	{
	  strcpy (parg, *targ);
	  parg += strlen (*targ);
	}
      *parg++ = ' ';
      targ++;
    }
  *--parg = '\0';

  memset (&start, 0, sizeof (start));
  start.cb = sizeof (start);

  start.dwFlags = STARTF_USESTDHANDLES;
  start.hStdInput = process->w_forkin;
  start.hStdOutput = process->w_forkout;
  /* child's stderr is always redirected to outfd */
  start.hStdError = process->w_forkout;

  /* Explicitly specify no security */
  if (!InitializeSecurityDescriptor (&sec_desc, SECURITY_DESCRIPTOR_REVISION))
    goto EH_Fail;
  if (!SetSecurityDescriptorDacl (&sec_desc, TRUE, NULL, FALSE))
    goto EH_Fail;
  sec_attrs.nLength = sizeof (sec_attrs);
  sec_attrs.lpSecurityDescriptor = &sec_desc;
  sec_attrs.bInheritHandle = FALSE;

  /* creating a new console allow easier close. Do not use
     CREATE_NEW_PROCESS_GROUP as this results in disabling Ctrl+C */
  flags = CREATE_NEW_CONSOLE;

  /* if app is not a gui application, hide the console */
  if (is_gui == FALSE) {
    start.dwFlags |= STARTF_USESHOWWINDOW;
    start.wShowWindow = SW_HIDE;
  }

  /* Set initial directory to null character to use current directory */
  if (!CreateProcess (NULL, cmdline, &sec_attrs, NULL, TRUE,
		      flags, env, NULL, &start, &process->procinfo))
    goto EH_Fail;

  pid = (int) process->procinfo.hProcess;
  process->pid=pid;

  return pid;

 EH_Fail:
  return -1;
}

/***********************
 ** gvd_send_header ()
 ***********************/

void
gvd_send_header (term_handler* p, char header[5], int size, int *ret)
{
  *ret = 0;
}

/********************************
 **  gvd_setup_communication ()
 ********************************/

int
gvd_setup_communication (term_handler** process_out) /* output param */
{
  term_handler* process;

  process = (term_handler *)malloc (sizeof (term_handler));
  ZeroMemory (process, sizeof (term_handler));
  *process_out = process;

  return 0;
}

int
gvd_setup_child_communication (term_handler* process, char** argv)
{
  int cpid;
  HANDLE parent;
  SECURITY_ATTRIBUTES sec_attrs;
  char slavePath [MAX_PATH];
  char **nargv;
  int argc;
  int i;
  char pipeNameIn[100];
  HANDLE hSlaveInDrv = NULL; /* Handle to communicate with slave driver */

  parent = GetCurrentProcess ();

  /* Set inheritance for the pipe handles */
  sec_attrs.nLength = sizeof (SECURITY_ATTRIBUTES);
  sec_attrs.bInheritHandle = TRUE;
  sec_attrs.lpSecurityDescriptor = NULL;

  /* Create in and out pipes */
  if (!CreatePipe (&process->w_forkin, &process->w_infd, &sec_attrs, 0))
    report_file_error ("Creation of child's IN handle", Qnil);
  if (!CreatePipe (&process->w_outfd, &process->w_forkout, &sec_attrs, 0))
    report_file_error ("Creation of child's OUT handle", Qnil);

  /* Do not inherit the parent's side of the pipes */
  SetHandleInformation (&process->w_infd, HANDLE_FLAG_INHERIT, 0);
  SetHandleInformation (&process->w_outfd, HANDLE_FLAG_INHERIT, 0);

  /* use native argv */
  nargv = argv;

  /* Spawn the child. */
  cpid = nt_spawnve (nargv[0], nargv, NULL, process);

  /* close the duplicated handles passed to the child */
  CloseHandle (process->w_forkout);
  CloseHandle (process->w_forkin);

  if (cpid == -1)
    /* An error occurred while trying to spawn the process.  */
    report_file_error ("Spawning child process", Qnil);

  return cpid;
 end:
  if (hSlaveInDrv != NULL)
    CloseHandle (hSlaveInDrv);
  return -1;
}

int
gvd_setup_parent_communication
  (term_handler* process, int* in, int* out, int* err, int* pid)
{
  process->infd = _open_osfhandle ((long) process->w_infd, 0);
  process->outfd = _open_osfhandle ((long) process->w_outfd, 0);
  *out = process->outfd;
  *in  = process->infd;
  /* child's stderr is always redirected to outfd */
  *err = *out;
  *pid = process->pid;
}

typedef struct _child_process
{
  HWND                  hwnd;
  PROCESS_INFORMATION   *procinfo;
} child_process;

static BOOL CALLBACK
find_child_console (HWND hwnd, child_process * cp)
{
  DWORD thread_id;
  DWORD process_id;

  thread_id = GetWindowThreadProcessId (hwnd, &process_id);
  if (process_id == cp->procinfo->dwProcessId)
    {
      char window_class[32];

      GetClassName (hwnd, window_class, sizeof (window_class));
      if (strcmp (window_class, "ConsoleWindowClass") == 0)
        {
          cp->hwnd = hwnd;
          return FALSE;
        }
    }
  /* keep looking */
  return TRUE;
}

int
gvd_interrupt_process (term_handler* p)
{
  DWORD exit_code;

  /* Call interrupt only if the process is still active. Indeed
   * process id are reused once released and we might otherwise
   * send a Ctrl-C to the wrong process.  */
  if (GetExitCodeProcess (p->procinfo.hProcess, &exit_code))
  {
    if (exit_code == STILL_ACTIVE)
    {
      return gvd_interrupt_pid (p->procinfo.dwProcessId);
    }
  }
  return 0;
}

int
gvd_interrupt_pid (int pid)
{
  volatile child_process cp;
  int rc = 0;

  cp.procinfo = (LPPROCESS_INFORMATION) malloc (sizeof (PROCESS_INFORMATION));
  cp.procinfo->dwProcessId = pid;
  cp.hwnd = INVALID_HANDLE_VALUE;

  /* Try to locate console window for process. */
  EnumWindows ((WNDENUMPROC) find_child_console, (LPARAM) &cp);

  if (cp.hwnd != INVALID_HANDLE_VALUE)
    {
      BYTE control_scan_code = (BYTE) MapVirtualKey (VK_CONTROL, 0);
      /* Retrieve Ctrl-C scancode */
      BYTE vk_break_code = 'C';
      BYTE break_scan_code = (BYTE) MapVirtualKey (vk_break_code, 0);
      HWND foreground_window;

      foreground_window = GetForegroundWindow ();
      if (foreground_window)
        {
          /* NT 5.0, and apparently also Windows 98, will not allow
             a Window to be set to foreground directly without the
             user's involvement. The workaround is to attach
             ourselves to the thread that owns the foreground
             window, since that is the only thread that can set the
             foreground window.  */
          DWORD foreground_thread, child_thread;

          foreground_thread =
            GetWindowThreadProcessId (foreground_window, NULL);
          if (foreground_thread == GetCurrentThreadId ()
              || !AttachThreadInput (GetCurrentThreadId (),
                                     foreground_thread, TRUE))
            foreground_thread = 0;

          child_thread = GetWindowThreadProcessId (cp.hwnd, NULL);
          if (child_thread == GetCurrentThreadId ()
              || !AttachThreadInput (GetCurrentThreadId (),
                                     child_thread, TRUE))
            child_thread = 0;

          /* Set the foreground window to the child.  */
          if (SetForegroundWindow (cp.hwnd))
            {
              /* Generate keystrokes as if user had typed Ctrl-Break or
                 Ctrl-C.  */
              keybd_event (VK_CONTROL, control_scan_code, 0, 0);
              keybd_event (vk_break_code, break_scan_code,
                (vk_break_code == 'C' ? 0 : KEYEVENTF_EXTENDEDKEY), 0);
              keybd_event (vk_break_code, break_scan_code,
                (vk_break_code == 'C' ? 0 : KEYEVENTF_EXTENDEDKEY)
                 | KEYEVENTF_KEYUP, 0);
              keybd_event (VK_CONTROL, control_scan_code, KEYEVENTF_KEYUP, 0);

              /* Sleep for a bit to give time for the main frame to respond
              to focus change events.  */
              Sleep (100);

              SetForegroundWindow (foreground_window);
            }
          /* Detach from the foreground and child threads now that
             the foreground switching is over.  */
          if (foreground_thread)
	    AttachThreadInput (GetCurrentThreadId (), foreground_thread, FALSE);
	  if (child_thread)
            AttachThreadInput (GetCurrentThreadId (), child_thread, FALSE);
        }
    }
  /* Ctrl-Break is NT equivalent of SIGINT.  */
  else if (!GenerateConsoleCtrlEvent
             (CTRL_BREAK_EVENT, cp.procinfo->dwProcessId))
    {
      errno = EINVAL;
      rc = -1;
    }

  free (cp.procinfo);
  return rc;
}

/* kill a process, as this implementation use CreateProcess on Win32 we need
   to use Win32 TerminateProcess API */
int
gvd_terminate_process (term_handler* p)
{
  close(p->infd);
  close(p->outfd);

  if (!TerminateProcess (p->procinfo.hProcess, 1))
    return -1;
  else
    return 0;
}

/* wait for process pid to terminate and return the process status. This
   implementation is different from the adaint.c one for Windows as it uses
   the Win32 API instead of the C one. */

int
gvd_waitpid (term_handler* p)
{
  int status = 0;

  DWORD exitcode;
  DWORD res;
  HANDLE proc_hand = p->procinfo.hProcess;

  res = WaitForSingleObject (proc_hand, 0);
  GetExitCodeProcess (proc_hand, &exitcode);

  CloseHandle (p->procinfo.hThread);
  CloseHandle (p->procinfo.hProcess);

  /* No need to close the handles: they were closed on the ada side */

  return (int) exitcode;
}

/********************************
 **  gvd_free_process ()
 ********************************/

void
gvd_free_process (void* process)
{
   free ((term_handler *)process);
}

/* TTY handling */

typedef struct {
  int tty_fd;        /* descriptor for the tty */
  char tty_name[24]; /* Name of TTY device */
} TTY_Handle;

int
gvd_tty_supported (void)
{
  return 0;
}

/* Return the tty name associated with p */

char *
gvd_tty_name (TTY_Handle* t)
{
  return t->tty_name;
}

int
gvd_tty_fd (TTY_Handle* t)
{
  return t->tty_fd;
}

TTY_Handle*
gvd_new_tty (void)
{
  return (TTY_Handle*)0;
}

void
gvd_reset_tty (TTY_Handle* t)
{
  return;
}

void
gvd_close_tty (TTY_Handle* t)
{
  free (t);
}

void
gvd_setup_winsize (void *desc, int rows, int columns)
{
}

int
__gnat_expect_poll (int *fd, int num_fd, int timeout, int *is_set)
{
#define MAX_DELAY 100

  int i, delay, infinite = 0;
  DWORD avail;
  HANDLE handles[num_fd];

  for (i = 0; i < num_fd; i++)
    is_set[i] = 0;

  for (i = 0; i < num_fd; i++)
    handles[i] = (HANDLE) _get_osfhandle (fd [i]);

  /* Start with small delays, and then increase them, to avoid polling too
     much when waiting a long time */
  delay = 5;

  if (timeout < 0)
    infinite = 1;

  while (1)
    {
      for (i = 0; i < num_fd; i++)
        {
          if (!PeekNamedPipe (handles [i], NULL, 0, NULL, &avail, NULL))
            return -1;

          if (avail > 0)
            {
              is_set[i] = 1;
              return 1;
            }
        }

      if (!infinite && timeout <= 0)
        return 0;

      Sleep (delay);
      timeout -= delay;

      if (delay < MAX_DELAY)
        delay += 10;
    }
}

#endif /* WIN32 */
#undef _GNU_SOURCE

#include "Python.h"

/* python signature: non_blocking_spawn() */
static PyObject *
non_blocking_spawn (PyObject *self, PyObject *args)
{
   PyObject *py_cmd_args = PyTuple_GetItem(args, 0);
   int py_cmd_args_n = PyTuple_Size (py_cmd_args);
   char *cmd_args[py_cmd_args_n + 1];
   int j;
   int pid, in_fd, out_fd, err_fd;
   term_handler *desc;
   PyObject *result;

   for (j=0; j<py_cmd_args_n; j++)
   {
     cmd_args[j] = PyString_AsString(PyTuple_GetItem(py_cmd_args, j));
   }


   cmd_args[py_cmd_args_n] = NULL;

   gvd_setup_communication(&desc);
#ifdef WIN32
   pid = 0;
#else
   pid = fork();
#endif
   if (pid == 0)
     gvd_setup_child_communication(desc, cmd_args);

   gvd_setup_parent_communication(desc, &in_fd, &out_fd, &err_fd, &pid);
   result = PyTuple_New(5);
   PyTuple_SetItem(result, 0, PyInt_FromLong((long) in_fd));
   PyTuple_SetItem(result, 1, PyInt_FromLong((long) out_fd));
   PyTuple_SetItem(result, 2, PyInt_FromLong((long) err_fd));
   PyTuple_SetItem(result, 3, PyInt_FromLong((long) pid));
   PyTuple_SetItem(result, 4, PyCObject_FromVoidPtr((void *) desc,
                   gvd_free_process));
   return result;
}

static PyObject *
poll (PyObject *self, PyObject *args)
{
  PyObject *fd_list = PyTuple_GetItem(args, 0);
  int num_fd = PyTuple_Size(fd_list);
  int timeout = PyInt_AsLong(PyTuple_GetItem (args, 1));
  int fd[num_fd];
  int index;
  int is_set[num_fd];
  int status;
  PyObject *result_inner, *result;

  for (index=0; index < num_fd; index++)
    fd[index] = PyInt_AsLong(PyTuple_GetItem(fd_list, index));

  status = __gnat_expect_poll (fd, num_fd, timeout, is_set);

  result_inner = PyTuple_New(num_fd);
  for (index=0; index < num_fd; index++)
    PyTuple_SetItem(result_inner, index,
                    PyInt_FromLong((long) is_set[index]));

  result = PyTuple_New(2);
  PyTuple_SetItem(result, 0, PyInt_FromLong((long) status));
  PyTuple_SetItem(result, 1, result_inner);
  return result;
}

static PyObject *
expect_read(PyObject *self, PyObject *args)
{
  int fd = (int) PyInt_AsLong(PyTuple_GetItem(args, 0));
  int size = (int) PyInt_AsLong(PyTuple_GetItem(args, 1));
  int read_status;
  char buffer[size];
  PyObject *result;

  read_status = read(fd, buffer, size);

  result = PyTuple_New(2);
  PyTuple_SetItem(result, 0, PyInt_FromLong((long) read_status));

  if (read_status > 0)
    {
      PyTuple_SetItem(result, 1,
                      PyString_FromStringAndSize(buffer, read_status));
    }
  else
    {
     Py_INCREF(Py_None);
     PyTuple_SetItem(result, 1, Py_None);
    }
  return result;
}

static PyObject *
expect_write (PyObject *self, PyObject *args)
{
  int fd = (int) PyInt_AsLong(PyTuple_GetItem(args, 0));
  int size = (int) PyString_Size(PyTuple_GetItem(args, 1));
  char *buffer = PyString_AsString(PyTuple_GetItem(args, 1));
  int write_status;

  write_status = write(fd, buffer, size);
  return PyInt_FromLong((long) write_status);
}

static PyObject *
expect_terminate_process (PyObject *self, PyObject *args)
{
  term_handler *desc =
    (term_handler *) PyCObject_AsVoidPtr(PyTuple_GetItem(args, 0));
  gvd_terminate_process(desc);
  Py_INCREF(Py_None);
  return Py_None;
}

static PyObject *
expect_interrupt_process(PyObject *self, PyObject *args)
{
  term_handler *desc =
    (term_handler *) PyCObject_AsVoidPtr(PyTuple_GetItem(args, 0));
  gvd_interrupt_process(desc);
  Py_INCREF(Py_None);
  return Py_None;
}

static PyObject *
expect_waitpid(PyObject *self, PyObject *args)
{
  int result;
  term_handler *desc =
    (term_handler *) PyCObject_AsVoidPtr(PyTuple_GetItem(args, 0));
  result = gvd_waitpid(desc);
  return PyInt_FromLong((long) result);
}

static PyMethodDef TermMethods[] =
{
  {"non_blocking_spawn", non_blocking_spawn, METH_VARARGS, "spawn a command"},
  {"poll", poll, METH_VARARGS, "poll"},
  {"read", expect_read, METH_VARARGS, "read"},
  {"write", expect_write, METH_VARARGS, "write"},
  {"waitpid", expect_waitpid, METH_VARARGS, "waitpid"},
  {"interrupt", expect_interrupt_process, METH_VARARGS, "interrupt"},
  {"terminate", expect_terminate_process, METH_VARARGS, "terminate"},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC
init_term(void)
{
  PyObject *m;
  m = Py_InitModule("_term", TermMethods);
}
