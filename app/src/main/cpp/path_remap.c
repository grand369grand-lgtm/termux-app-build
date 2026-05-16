#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <dirent.h>
#include <stdarg.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <limits.h>

static const char OLD_PREFIX[] = "/data/data/com.termux";
static const char NEW_PREFIX[] = "/data/data/com.anroot";
#define OLD_LEN (sizeof(OLD_PREFIX) - 1)
#define NEW_LEN (sizeof(NEW_PREFIX) - 1)

static __thread char remap_buf[PATH_MAX * 2];

static void *get_real_func(const char *name) {
    void *func = dlsym(RTLD_NEXT, name);
    if (!func) {
        fprintf(stderr, "anroot-remap: failed to find real %s\n", name);
        abort();
    }
    return func;
}

static const char *remap_path(const char *path) {
    if (!path) return NULL;
    if (strncmp(path, OLD_PREFIX, OLD_LEN) == 0) {
        memcpy(remap_buf, NEW_PREFIX, NEW_LEN);
        strncpy(remap_buf + NEW_LEN, path + OLD_LEN, sizeof(remap_buf) - NEW_LEN - 1);
        remap_buf[sizeof(remap_buf) - 1] = '\0';
        return remap_buf;
    }
    return path;
}

static const char *remap(const char *path) {
    if (!path) return NULL;
    return remap_path(path);
}

/* Define typedefs for function pointers */
typedef int (*open_fn)(const char *, int, ...);
typedef int (*open64_fn)(const char *, int, ...);
typedef int (*openat_fn)(int, const char *, int, ...);
typedef int (*creat_fn)(const char *, mode_t);
typedef int (*stat_fn)(const char *, struct stat *);
typedef int (*stat64_fn)(const char *, struct stat64 *);
typedef int (*lstat_fn)(const char *, struct stat *);
typedef int (*lstat64_fn)(const char *, struct stat64 *);
typedef int (*fstatat_fn)(int, const char *, struct stat *, int);
typedef int (*fstatat64_fn)(int, const char *, struct stat64 *, int);
typedef DIR *(*opendir_fn)(const char *);
typedef int (*mkdir_fn)(const char *, mode_t);
typedef int (*mkdirat_fn)(int, const char *, mode_t);
typedef int (*rmdir_fn)(const char *);
typedef int (*access_fn)(const char *, int);
typedef int (*faccessat_fn)(int, const char *, int, int);
typedef int (*chmod_fn)(const char *, mode_t);
typedef int (*fchmodat_fn)(int, const char *, mode_t, int);
typedef int (*chown_fn)(const char *, uid_t, gid_t);
typedef int (*fchownat_fn)(int, const char *, uid_t, gid_t, int);
typedef int (*unlink_fn)(const char *);
typedef int (*unlinkat_fn)(int, const char *, int);
typedef int (*rename_fn)(const char *, const char *);
typedef int (*renameat_fn)(int, const char *, int, const char *);
typedef int (*link_fn)(const char *, const char *);
typedef int (*linkat_fn)(int, const char *, int, const char *, int);
typedef int (*symlink_fn)(const char *, const char *);
typedef int (*symlinkat_fn)(const char *, int, const char *);
typedef ssize_t (*readlink_fn)(const char *, char *, size_t);
typedef ssize_t (*readlinkat_fn)(int, const char *, char *, size_t);
typedef int (*truncate_fn)(const char *, off_t);
typedef int (*truncate64_fn)(const char *, off64_t);
typedef int (*execve_fn)(const char *, char *const *, char *const *);
typedef char *(*realpath_fn)(const char *, char *);

/* Helper macro to get real function */
#define REAL(type, name) ((type)get_real_func(#name))

/* File access */
int open(const char *path, int flags, ...) {
    static open_fn real = NULL;
    if (!real) real = REAL(open_fn, open);
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        return real(remap(path), flags, mode);
    }
    return real(remap(path), flags);
}

int open64(const char *path, int flags, ...) {
    static open64_fn real = NULL;
    if (!real) real = REAL(open64_fn, open64);
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        return real(remap(path), flags, mode);
    }
    return real(remap(path), flags);
}

int openat(int dirfd, const char *path, int flags, ...) {
    static openat_fn real = NULL;
    if (!real) real = REAL(openat_fn, openat);
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
        return real(dirfd, remap(path), flags, mode);
    }
    return real(dirfd, remap(path), flags);
}

int creat(const char *path, mode_t mode) {
    static creat_fn real = NULL;
    if (!real) real = REAL(creat_fn, creat);
    return real(remap(path), mode);
}

/* Stat */
int stat(const char *path, struct stat *buf) {
    static stat_fn real = NULL;
    if (!real) real = REAL(stat_fn, stat);
    return real(remap(path), buf);
}

int stat64(const char *path, struct stat64 *buf) {
    static stat64_fn real = NULL;
    if (!real) real = REAL(stat64_fn, stat64);
    return real(remap(path), buf);
}

int lstat(const char *path, struct stat *buf) {
    static lstat_fn real = NULL;
    if (!real) real = REAL(lstat_fn, lstat);
    return real(remap(path), buf);
}

int lstat64(const char *path, struct stat64 *buf) {
    static lstat64_fn real = NULL;
    if (!real) real = REAL(lstat64_fn, lstat64);
    return real(remap(path), buf);
}

int fstatat(int dirfd, const char *path, struct stat *buf, int flags) {
    static fstatat_fn real = NULL;
    if (!real) real = REAL(fstatat_fn, fstatat);
    return real(dirfd, remap(path), buf, flags);
}

int fstatat64(int dirfd, const char *path, struct stat64 *buf, int flags) {
    static fstatat64_fn real = NULL;
    if (!real) real = REAL(fstatat64_fn, fstatat64);
    return real(dirfd, remap(path), buf, flags);
}

/* Directory */
DIR *opendir(const char *path) {
    static opendir_fn real = NULL;
    if (!real) real = REAL(opendir_fn, opendir);
    return real(remap(path));
}

int mkdir(const char *path, mode_t mode) {
    static mkdir_fn real = NULL;
    if (!real) real = REAL(mkdir_fn, mkdir);
    return real(remap(path), mode);
}

int mkdirat(int dirfd, const char *path, mode_t mode) {
    static mkdirat_fn real = NULL;
    if (!real) real = REAL(mkdirat_fn, mkdirat);
    return real(dirfd, remap(path), mode);
}

int rmdir(const char *path) {
    static rmdir_fn real = NULL;
    if (!real) real = REAL(rmdir_fn, rmdir);
    return real(remap(path));
}

/* File ops */
int access(const char *path, int mode) {
    static access_fn real = NULL;
    if (!real) real = REAL(access_fn, access);
    return real(remap(path), mode);
}

int faccessat(int dirfd, const char *path, int mode, int flags) {
    static faccessat_fn real = NULL;
    if (!real) real = REAL(faccessat_fn, faccessat);
    return real(dirfd, remap(path), mode, flags);
}

int chmod(const char *path, mode_t mode) {
    static chmod_fn real = NULL;
    if (!real) real = REAL(chmod_fn, chmod);
    return real(remap(path), mode);
}

int fchmodat(int dirfd, const char *path, mode_t mode, int flags) {
    static fchmodat_fn real = NULL;
    if (!real) real = REAL(fchmodat_fn, fchmodat);
    return real(dirfd, remap(path), mode, flags);
}

int chown(const char *path, uid_t owner, gid_t group) {
    static chown_fn real = NULL;
    if (!real) real = REAL(chown_fn, chown);
    return real(remap(path), owner, group);
}

int fchownat(int dirfd, const char *path, uid_t owner, gid_t group, int flags) {
    static fchownat_fn real = NULL;
    if (!real) real = REAL(fchownat_fn, fchownat);
    return real(dirfd, remap(path), owner, group, flags);
}

int unlink(const char *path) {
    static unlink_fn real = NULL;
    if (!real) real = REAL(unlink_fn, unlink);
    return real(remap(path));
}

int unlinkat(int dirfd, const char *path, int flags) {
    static unlinkat_fn real = NULL;
    if (!real) real = REAL(unlinkat_fn, unlinkat);
    return real(dirfd, remap(path), flags);
}

int rename(const char *oldpath, const char *newpath) {
    static rename_fn real = NULL;
    if (!real) real = REAL(rename_fn, rename);
    return real(remap(oldpath), remap(newpath));
}

int renameat(int olddirfd, const char *oldpath, int newdirfd, const char *newpath) {
    static renameat_fn real = NULL;
    if (!real) real = REAL(renameat_fn, renameat);
    return real(olddirfd, remap(oldpath), newdirfd, remap(newpath));
}

int link(const char *oldpath, const char *newpath) {
    static link_fn real = NULL;
    if (!real) real = REAL(link_fn, link);
    return real(remap(oldpath), remap(newpath));
}

int linkat(int olddirfd, const char *oldpath, int newdirfd, const char *newpath, int flags) {
    static linkat_fn real = NULL;
    if (!real) real = REAL(linkat_fn, linkat);
    return real(olddirfd, remap(oldpath), newdirfd, remap(newpath), flags);
}

int symlink(const char *target, const char *linkpath) {
    static symlink_fn real = NULL;
    if (!real) real = REAL(symlink_fn, symlink);
    return real(target, remap(linkpath));
}

int symlinkat(const char *target, int newdirfd, const char *linkpath) {
    static symlinkat_fn real = NULL;
    if (!real) real = REAL(symlinkat_fn, symlinkat);
    return real(target, newdirfd, remap(linkpath));
}

ssize_t readlink(const char *path, char *buf, size_t bufsiz) {
    static readlink_fn real = NULL;
    if (!real) real = REAL(readlink_fn, readlink);
    return real(remap(path), buf, bufsiz);
}

ssize_t readlinkat(int dirfd, const char *path, char *buf, size_t bufsiz) {
    static readlinkat_fn real = NULL;
    if (!real) real = REAL(readlinkat_fn, readlinkat);
    return real(dirfd, remap(path), buf, bufsiz);
}

int truncate(const char *path, off_t length) {
    static truncate_fn real = NULL;
    if (!real) real = REAL(truncate_fn, truncate);
    return real(remap(path), length);
}

int truncate64(const char *path, off64_t length) {
    static truncate64_fn real = NULL;
    if (!real) real = REAL(truncate64_fn, truncate64);
    return real(remap(path), length);
}

/* Exec */
int execve(const char *path, char *const argv[], char *const envp[]) {
    static execve_fn real = NULL;
    if (!real) real = REAL(execve_fn, execve);
    return real(remap(path), argv, envp);
}

/* Realpath */
char *realpath(const char *path, char *resolved) {
    static realpath_fn real = NULL;
    if (!real) real = REAL(realpath_fn, realpath);
    return real(remap(path), resolved);
}
