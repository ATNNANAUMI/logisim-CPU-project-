"""The disk's filesystem, TFS1. The C library (compiler/libc/fs.c) reads and
writes the same format; this module is the reference.

The disk image is a file of 32-bit little-endian words (cpu_sim's Disk
device, 0x8C/0x8D). Numbers below are words. One block = 256 words.

    block 0         superblock: MAGIC, VERSION, BLOCK, block count N,
                    FAT start block (1), FAT block count F = ceil(N / 256),
                    the root directory's first block and its length
    blocks 1 .. F   the FAT, one word per block: FREE (0), END (0xFFFFFFFF)
                    for the last block of a chain, else the next block.
                    Blocks 0 .. F are marked END (used)
    block F + 1     the root directory's first block; the rest is data

A file is a chain of blocks (first block 0 = an empty file, no blocks). A
directory is a file of ENTRY-word entries: the name (NAME_WORDS words, one
char per word, 0-terminated, at most MAX_NAME chars, no '/'), the first
block, the length, the flags (USED, DIR, PACKED) and one reserved word. A
deleted entry has flags 0 and is reused; directories never shrink. '.' and
'..' are worked out from the path, not stored. A directory's own first
block and length are in its entry (the root's in the superblock).

A text file (PACKED) holds 4 chars a word, char k in bits 8 * (k % 4) of
word k // 4, so the image's bytes read as the text on the PC; its length
counts chars. A binary file holds one word per element; its length counts
words. New blocks are filled with zeros.
"""

import mmap
import os
import struct

MAGIC = 0x31534654              # b"TFS1" as a little-endian word
VERSION = 1
BLOCK = 256
FREE = 0
END = 0xFFFFFFFF
ENTRY = 132
NAME_WORDS = 128
MAX_NAME = NAME_WORDS - 1
USED, DIR, PACKED = 1, 2, 4

# superblock words
SB_MAGIC, SB_VERSION, SB_BLOCK, SB_BLOCKS, SB_FAT, SB_FAT_BLOCKS, SB_ROOT, SB_ROOT_LEN = range(8)
# words of an entry after the name
E_FIRST, E_LENGTH, E_FLAGS = NAME_WORDS, NAME_WORDS + 1, NAME_WORDS + 2

WORD = struct.Struct("<I")
MIN_BLOCKS = 4                  # superblock, a FAT block, the root, one data block


class FsError(Exception):
    pass


def fat_blocks(blocks):
    return (blocks + BLOCK - 1) // BLOCK


def pack(data: bytes) -> list:
    """Bytes -> words, 4 per word, the first in the low bits."""
    data = data + bytes(-len(data) % 4)
    return list(struct.unpack(f"<{len(data) // 4}I", data))


def unpack(words, length) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)[:length]


def split(path: str) -> list:
    """'/a/./b/../c' -> ['a', 'c']; every path is from the root."""
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return parts


def check_name(name: str) -> None:
    if not name or len(name) > MAX_NAME:
        raise FsError(f"{name!r}: a name is 1 to {MAX_NAME} characters")
    if any(c in "/ " or ord(c) < 32 for c in name):
        raise FsError(f"{name!r}: no '/', spaces or control characters in a name")


class Node:
    """A file or directory: where its entry is, and what it says.
    parent is None for the root (its first block and length are in the
    superblock); else the directory Node holding entry number index."""

    def __init__(self, name, first, length, flags, parent=None, index=None):
        self.name, self.first, self.length, self.flags = name, first, length, flags
        self.parent, self.index = parent, index

    @property
    def is_dir(self):
        return bool(self.flags & DIR)

    @property
    def packed(self):
        return bool(self.flags & PACKED)


class FileSystem:
    def __init__(self, path):
        self.path = str(path)
        self.file = open(self.path, "r+b")
        size = os.fstat(self.file.fileno()).st_size
        if size < MIN_BLOCKS * BLOCK * 4 or size % 4:
            self.file.close()
            raise FsError(f"{self.path}: not a disk image ({size} bytes)")
        self.map = mmap.mmap(self.file.fileno(), size)
        self.words = size // 4
        if self.word(SB_MAGIC) != MAGIC:
            self.close()
            raise FsError(f"{self.path}: not formatted (no TFS1 superblock): "
                          "python compiler/src/disk format IMG")
        if self.word(SB_VERSION) != VERSION or self.word(SB_BLOCK) != BLOCK:
            self.close()
            raise FsError(f"{self.path}: TFS1 version {self.word(SB_VERSION)}, "
                          f"block size {self.word(SB_BLOCK)}: not supported")
        self.blocks = self.word(SB_BLOCKS)
        self.fat_start = self.word(SB_FAT)
        self.hint = 0                       # where to start looking for a free block

    # ------------------------------------------------------------ format
    @staticmethod
    def format(path, words):
        """Make an empty filesystem of `words` words (a whole number of
        blocks), creating or overwriting the image file (sparse)."""
        blocks = words // BLOCK
        if blocks < MIN_BLOCKS:
            raise FsError(f"a disk needs at least {MIN_BLOCKS * BLOCK} words")
        fat = fat_blocks(blocks)
        root = fat + 1
        if root >= blocks:
            raise FsError("disk too small")
        with open(path, "wb") as f:
            f.truncate(blocks * BLOCK * 4)
            header = [MAGIC, VERSION, BLOCK, blocks, 1, fat, root, 0]
            f.write(struct.pack(f"<{len(header)}I", *header))
            f.seek(BLOCK * 4)                               # the FAT
            f.write(struct.pack(f"<{root + 1}I", *[END] * (root + 1)))
        return FileSystem(path)

    def close(self):
        if not self.map.closed:
            self.map.flush()
            self.map.close()
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------ words
    def word(self, i):
        return WORD.unpack_from(self.map, i * 4)[0]

    def set_word(self, i, value):
        WORD.pack_into(self.map, i * 4, value & 0xFFFFFFFF)

    def fat(self, block):
        return self.word(self.fat_start * BLOCK + block)

    def set_fat(self, block, value):
        self.set_word(self.fat_start * BLOCK + block, value)

    # ------------------------------------------------------------ blocks
    def free_blocks(self):
        return sum(1 for b in range(self.blocks) if self.fat(b) == FREE)

    def alloc(self):
        for n in range(self.blocks):
            b = (self.hint + n) % self.blocks
            if self.fat(b) == FREE:
                self.set_fat(b, END)
                self.hint = b + 1
                self.map[b * BLOCK * 4:(b + 1) * BLOCK * 4] = bytes(BLOCK * 4)
                return b
        raise FsError("disk full")

    def chain(self, first):
        blocks = []
        b = first
        while b != 0 and b != END:
            if b >= self.blocks or len(blocks) > self.blocks:
                raise FsError(f"broken chain from block {first}")
            blocks.append(b)
            b = self.fat(b)
        return blocks

    def free_chain(self, first):
        for b in self.chain(first):
            self.set_fat(b, FREE)
        self.hint = 0

    # ------------------------------------------------------------ file words
    def read(self, node, start=0, count=None):
        """Words start .. start + count of a file's blocks (to its last block)."""
        blocks = self.chain(node.first)
        end = len(blocks) * BLOCK if count is None else start + count
        out = []
        for i in range(start, end):
            out.append(self.word(blocks[i // BLOCK] * BLOCK + i % BLOCK))
        return out

    def write(self, node, start, words):
        """Write words at word `start` of a file, adding blocks as needed
        (node.first changes when the file had none; the caller saves it)."""
        blocks = self.chain(node.first)
        need = (start + len(words) + BLOCK - 1) // BLOCK
        while len(blocks) < need:
            b = self.alloc()
            if blocks:
                self.set_fat(blocks[-1], b)
            else:
                node.first = b
            blocks.append(b)
        for n, value in enumerate(words):
            i = start + n
            self.set_word(blocks[i // BLOCK] * BLOCK + i % BLOCK, value)

    def save(self, node):
        """Write a node's first block, length and flags back to its entry."""
        if node.parent is None:
            self.set_word(SB_ROOT, node.first)
            self.set_word(SB_ROOT_LEN, node.length)
            return
        self.write(node.parent, node.index * ENTRY + E_FIRST,
                   [node.first, node.length, node.flags])

    # ------------------------------------------------------------ directories
    def root(self):
        return Node("/", self.word(SB_ROOT), self.word(SB_ROOT_LEN), USED | DIR)

    def entries(self, directory):
        """The directory's used entries, as Nodes."""
        words = self.read(directory, 0, directory.length)
        out = []
        for index in range(directory.length // ENTRY):
            e = words[index * ENTRY:(index + 1) * ENTRY]
            if e[E_FLAGS] & USED:
                name = "".join(chr(c) for c in e[:NAME_WORDS][:e.index(0)])
                out.append(Node(name, e[E_FIRST], e[E_LENGTH], e[E_FLAGS], directory, index))
        return out

    def find(self, directory, name):
        for node in self.entries(directory):
            if node.name == name:
                return node
        return None

    def lookup(self, path):
        """The Node at path, or None."""
        node = self.root()
        for part in split(path):
            if not node.is_dir:
                return None
            node = self.find(node, part)
            if node is None:
                return None
        return node

    def parent_of(self, path):
        """(directory Node, last name) for a path to create or remove."""
        parts = split(path)
        if not parts:
            raise FsError("the root directory has no name")
        directory = self.lookup("/" + "/".join(parts[:-1]))
        if directory is None or not directory.is_dir:
            raise FsError(f"{'/' + '/'.join(parts[:-1])}: no such directory")
        check_name(parts[-1])
        return directory, parts[-1]

    def add_entry(self, directory, name, flags):
        """A new entry in directory (reusing a free one); returns its Node."""
        words = self.read(directory, 0, directory.length)
        count = directory.length // ENTRY
        index = next((i for i in range(count) if not words[i * ENTRY + E_FLAGS] & USED), count)
        name_words = [ord(c) for c in name] + [0] * (NAME_WORDS - len(name))
        node = Node(name, 0, 0, flags | USED, directory, index)
        self.write(directory, index * ENTRY, name_words + [0, 0, node.flags, 0])
        if index == count:
            directory.length += ENTRY
        self.save(directory)                # first block or length may have changed
        return node

    def remove_entry(self, node):
        self.free_chain(node.first)
        self.write(node.parent, node.index * ENTRY + E_FLAGS, [0])

    def check(self):
        """Problems with the disk, as text: a block used by two chains, a
        used block nobody reaches (leaked), a length past a file's blocks,
        a broken chain. An empty list = consistent."""
        problems = []
        owner = {b: "the superblock and FAT"
                 for b in range(self.fat_start + fat_blocks(self.blocks))}

        def walk(node, path):
            try:
                chain = self.chain(node.first)
            except FsError as e:
                problems.append(f"{path}: {e}")
                return
            for b in chain:
                if b in owner:
                    problems.append(f"block {b}: in {path} and in {owner[b]}")
                owner[b] = path
            words = (node.length + 3) // 4 if node.packed else node.length
            if words > len(chain) * BLOCK:
                problems.append(f"{path}: length {node.length} past its {len(chain)} blocks")
            if node.is_dir:
                for child in self.entries(node):
                    walk(child, path.rstrip("/") + "/" + child.name)

        walk(self.root(), "/")
        for b in range(self.blocks):
            if self.fat(b) != FREE and b not in owner:
                problems.append(f"block {b}: used but in no file (leaked)")
        return problems

    # ------------------------------------------------------------ commands
    def put(self, path, data: bytes, binary=False):
        """Create or replace a file: text (packed bytes) or binary (data is
        little-endian words, zero-padded to a whole word)."""
        directory, name = self.parent_of(path)
        node = self.find(directory, name)
        if node is not None and node.is_dir:
            raise FsError(f"{path}: is a directory")
        words = pack(data)
        flags = USED if binary else USED | PACKED
        if node is None:
            node = self.add_entry(directory, name, flags)
        else:
            self.free_chain(node.first)
            node.first, node.flags = 0, flags
        self.write(node, 0, words)
        node.length = len(words) if binary else len(data)
        self.save(node)
        return node

    def get(self, path) -> bytes:
        node = self.lookup(path)
        if node is None:
            raise FsError(f"{path}: no such file")
        if node.is_dir:
            raise FsError(f"{path}: is a directory")
        if node.packed:
            return unpack(self.read(node, 0, (node.length + 3) // 4), node.length)
        return unpack(self.read(node, 0, node.length), node.length * 4)

    def mkdir(self, path):
        directory, name = self.parent_of(path)
        if self.find(directory, name) is not None:
            raise FsError(f"{path}: already exists")
        return self.add_entry(directory, name, DIR)

    def remove(self, path, directory=False):
        node = self.lookup(path)
        if node is None or node.parent is None:
            raise FsError(f"{path}: no such {'directory' if directory else 'file'}")
        if node.is_dir != directory:
            raise FsError(f"{path}: is {'not ' if directory else ''}a directory")
        if directory and self.entries(node):
            raise FsError(f"{path}: directory not empty")
        self.remove_entry(node)

    def rename(self, old, new):
        node = self.lookup(old)
        if node is None or node.parent is None:
            raise FsError(f"{old}: no such file")
        directory, name = self.parent_of(new)
        if self.find(directory, name) is not None:
            raise FsError(f"{new}: already exists")
        if node.is_dir:                             # not into itself
            here = split(old)
            if split(new)[:len(here)] == here:
                raise FsError(f"{new}: inside {old}")
        moved = self.add_entry(directory, name, node.flags & ~USED)
        moved.first, moved.length = node.first, node.length
        self.save(moved)
        old_node = self.lookup(old)                 # its parent may have grown
        self.write(old_node.parent, old_node.index * ENTRY + E_FLAGS, [0])
