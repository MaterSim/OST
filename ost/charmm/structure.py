from io import StringIO

from parmed import Structure
from parmed.charmm import CharmmCrdFile, CharmmParameterSet, CharmmPsfFile

from ost.interfaces.parmed import ParmEdStructure
from ost.utils import accurate_round

INP_TEMPLATE = """
! Automated Charmm calculation

bomlev -1
Read rtf card name {rtf:}
Read param card name {prm:}

Read sequence card
* Reading the coordinates of residue
*
{res:}
Generate main first none last none setup warn
Read coor card free
* Residues coordinate
*
{crd:}
coor stat select all end
crys defi {shape:} {cry:}
crys build cutoff {cutoff:}
! image byres xcen ?xave ycen ?yave zcen ?zave sele resn UNK end

Update inbfreq 10 imgfreq 10 ihbfreq 10 -
ewald pmewald -
lrc fftx {fftx:} ffty {ffty:} fftz {fftz} -
kappa {gewald:} order 6 qcor 1.0 -
fswitch atom vatom vfswitch !
Energy ihbfrq 0 inbfq -1
Open write card unit 14 name tmp.out
Write energy card unit 14
* UNL energy before optimization
*
Energy
Write energy card unit 14
* UNL energy after optimization
*
Write coor pdb name tmp.pdb
* CELL :  ?xtla  ?xtlb  ?xtlc ?xtlalpha ?xtlbeta ?xtlgamma
* Energy(kcal): ?ener
*


"""


class CHARMMStructure(ParmEdStructure):

    _progname = "CHARMM"

    @property
    def atomtypes_with_resname(self):
        if not hasattr(self, "_atomtype_with_resname"):
            ps = self.get_parameterset_with_resname_as_prefix()
            self._atomtypes_with_resname = ps.atom_types
        return self._atomtypes_with_resname


    def write_inp(self, of, base: str):

        io = StringIO()
        io.write(str(len(self.atoms)) + "\n")
        if self.box is not None:
            ase = self.to_ase()
            for i, (atom, pos) in enumerate(zip(self.atoms, ase.get_scaled_positions(wrap=False)), 1):
                io.write(
                    "{:5d} {:5d} {:5s} {:5s} {:9.5f} {:9.5f} {:9.5f}\n".format(
                        i, atom.residue.number + 1, atom.residue.name, atom.name, *pos
                    )
                )
            shape = "triclinic"
            cry = "{0} {1} {2} {3} {4} {5}".format(*self.box)
            io.write(f"coor conv FRAC SYMM {cry:}\n")
        else:
            for i, (atom, pos) in enumerate(zip(self.atoms, self.coordinates), 1):
                io.write(
                    "{:5d} {:5d} {:5s} {:5s} {:9.5f} {:9.5f} {:9.5f}\n".format(
                        i, atom.residue.number + 1, atom.residue.name, atom.name, *pos
                    )
                )
            shape = "cubic"
            cry = "{0} {1} {2} {3} {4} {5}".format(*self.LARGEBOX)
        residues = str(len(self.residues)) + "\n"
        for res in self.residues:
            residues += f"{res.name}\n"
        fftx, ffty, fftz = self.fftgrid
        inp = INP_TEMPLATE.format(
            crd=io.getvalue(),
            rtf=base + ".rtf",
            prm=base + ".prm",
            res=residues,
            cutoff=str(self.cutoff_coul),
            gewald=str(self.gewald),
            fftx=fftx,
            ffty=ffty,
            fftz=fftz,
            cry=cry,
            shape=shape,
        )
        return of.write(inp)

    def write_prm(self, of):
        of.write("*>>>> CHARMM Parameter file generated by molsppre \n")
        of.write("* \n")
        of.write("\n")

        of.write("BOND\n")
        dic = self.get_keys_and_types(self.bonds)
        for k, t in dic.items():
            of.write("%2s %2s %9.5f %9.5f\n" % (*k, t.k, t.req))
        of.write("\nANGLE\n")
        dic = self.get_keys_and_types(self.angles)
        for k, t in dic.items():
            of.write("%2s %2s %2s %9.5f   %10.5f\n" % (*k, t.k, t.theteq))
        of.write("\nDIHEDRAL\n")
        #imps = []
        #for d in self.dihedrals:
        #    if d.improper:
        #        imps.append(d.type) #print(d.type)
        dic = self.get_keys_and_types(self.dihedrals)
        #for k, t in dic.items(): print(*k[0])
        imp = StringIO()
        for k, t in dic.items():
            #print(k)
            if not k[1][1]: #t not in imps:
                of.write("%2s %2s %2s %2s %9.6f %6d %7.3f\n" % (*k[0], t.phi_k, t.per, t.phase))
            else:
                imp.write("%2s %2s %2s %2s %9.6f %6d %7.3f\n" % (*k[0], t.phi_k, t.per, t.phase))
        of.write("\nIMPHI\n")
        of.write(imp.getvalue())
        # NONBONDED  NBXMOD 5  GROUP SWITCH CDIEL -
        of.write(
            f"""\n
NONBONDED  NBXMOD 5  ATOM CDIEL FSHIFT VATOM VDISTANCE VFSWITCH GROUP -
CUTNB {self.cutoff_ljout + self.cutoff_skin}  CTOFNB {self.cutoff_ljout}  CTONNB {self.cutoff_ljin}  EPS 1.0  E14FAC 0.83333333  WMIN 1.5
!                Emin     Rmin/2              Emin/2     Rmin  (for 1-4's)
!             (kcal/mol)    (A)
"""
        )
        #for (k, at) in self.parameterset.atom_types.items():
        fmt = "%2s %9.3f %9.5f %9.5f %9.5f %9.5f %9.5f\n"
        names = []
        for (k, at) in self.atomtypes_with_resname.items():
            at_name = at.name[3:]
            if at_name not in names:
                heps = -at.epsilon * 0.5
                heps = accurate_round(-0.5 * at.epsilon)
                if at.rmin == 0 or at.epsilon == 0:
                    of.write(fmt % (at_name, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
                else:
                    of.write(fmt % (at_name, 0.0, -at.epsilon, at.rmin, 0.0, heps, at.rmin))
                names.append(at_name)
        of.write("\nEND\n")

    def get_atom_info(self):
        """
        create the residue and atom_labeling information as a dict
        used for creating the charmm input
        """
        atom_info = {'resName': [], 'label': []}
        for res in self.residues:
            atom_info['resName'].append(res.name)
            _labels = [at.name for at in res.atoms]
            atom_info['label'].append(_labels)
        return atom_info


    def write_rtf(self, of):
        """
        Create the rtf file
        """
        of.write("* Topology File.\n")
        of.write("* \n")
        of.write("   99   1\n")

        i = 1
        for (k, at) in self.parameterset.atom_types.items():
            of.write("MASS %5d %-5s %10.6f\n" % (i, k, at.mass))
            i += 1

        resorgs, resnames = self.get_unique_residue()
        sios = {}
        for name in resnames:
            sios[name] = StringIO()

        reschgs = [0] * len(resnames)
        for at in self.each_atoms_only_unique_residue():
            if at.residue.number in resorgs.keys():
                reschgs[at.residue.number - self.count0] += at.charge

        for count, (resname, sio) in enumerate(sios.items()):
            #sio.write(f"\nRESI {resname}  0.000\n")
            sio.write("\nRESI {:s}  {:8.6f}\n".format(resname, reschgs[count]))
            sio.write("GROUP\n")

        for at in self.each_atoms_only_unique_residue():
            if at.residue.number in resorgs.keys():
                sio = sios[at.residue.name]
                sio.write("ATOM %-5s %-5s %10.6f\n" % (at.name, at.type, at.charge))
        sio.write("\n")

        for b in self.bonds:
            a1 = b.atom1
            a2 = b.atom2
            assert a1.residue == a2.residue
            if a1.residue.number in resorgs.keys():
                sio = sios[a1.residue.name]
                sio.write(
                    "BOND %-5s %-5s  ! d,E,order=%6.4f,%6.4f,%3.1f\n" % (a1.name, a2.name, b.measure(), b.energy(), b.order)
                )
        for _resname, sio in sios.items():
            sio.write("\n")

        for a in self.angles:
            a1 = a.atom1
            a2 = a.atom2
            a3 = a.atom3
            assert a1.residue == a2.residue
            assert a1.residue == a3.residue
            if a1.residue.number in resorgs.keys():
                angle = a.measure()
                ene = a.energy()
                sio = sios[a1.residue.name]
                sio.write("ANGL %-5s %-5s %-5s  ! ang,E=%6.4f,%6.4f\n" % (a1.name, a2.name, a3.name, angle, ene))
        for _resname, sio in sios.items():
            sio.write("\n")

        lastd = None
        for d in self.dihedrals:
            # if d.ignore_end and not d.improper:
            #    continue
            if lastd is not None and lastd.same_atoms(d):
                continue
            a1 = d.atom1
            a2 = d.atom2
            a3 = d.atom3
            a4 = d.atom4
            assert a1.residue == a2.residue
            assert a1.residue == a3.residue
            assert a1.residue == a4.residue
            if a1.residue.number in resorgs.keys():
                dihe = d.measure()
                ene = d.energy()
                sio = sios[a1.residue.name]
                if not d.improper:
                    sio.write(
                        "DIHE %-5s %-5s %-5s %-5s ! dihe,E=%6.4f,%6.4f\n" % (a1.name, a2.name, a3.name, a4.name, dihe, ene)
                    )
                else:
                    sio.write(
                        "IMPH %-5s %-5s %-5s %-5s ! dihe,E=%6.4f,%6.4f\n" % (a1.name, a2.name, a3.name, a4.name, dihe, ene)
                    )
            lastd = d
        for sio in sios.values():
            of.write(sio.getvalue())
            of.write("\n")
        of.write("\n")

    def get_charmm_info(self):

        labels = [[]]
        i = 0
        cres = self.residues[0].name
        resName = [cres]
        for atom, _utype in self.each_atoms_only_unique_residue(with_unique_type=True):
            if atom.residue.name != cres:
                cres = atom.residue.name
                i += 1
                labels.append([])
                resName.append(cres)
            labels[i].append(atom.name)

        charmm_info = {
            "label": labels,
            "resName": resName,
            "rtf": self.get_str_with_writer(self.write_rtf),
            "prm": self.get_str_with_writer(self.write_prm),
        }
        return charmm_info

    def to_ase(self, *args, **kwargs):
        ase = super().to_ase(*args, **kwargs)
        ase.info["charmm"] = self.get_charmm_info()
        return ase

    @staticmethod
    def write_charmmfiles_by_parmd(structure: Structure, base="ff_parmd"):
        """
        for validation
        """
        frtf = f"{base}.rtf"
        fprm = f"{base}.prm"
        fstr = f"{base}.str"
        #fcrd = f"{base}.crd"
        cps = CharmmParameterSet.from_structure(structure)
        cps.write(top=frtf, par=fprm, str=fstr)
        #CharmmCrdFile.write(structure, fcrd)

    def write_charmmfiles(self, base: str = "charmm"):
        """
        Dump CHARMM inputs to files
        """
        self.write_rtf(open(base + ".rtf", "w"))
        self.write_prm(open(base + ".prm", "w"))


def check_prm(path):
    """
    Todo: move it to charmm interface
    Sometimes there are something wrong with prm file (RUBGIH),
    """
    with open(path, "r") as f:
        lines = f.readlines()
        pairs = []
        triplets = []
        imphis = []
        ids = []
        do_angle = False
        do_bond = False
        do_dihedral = False
        do_imphi = False
        for i, l in enumerate(lines):
            tmp = l.split()
            if l.find("ANGLE") == 0:
                do_angle = True
            elif l.find("BOND") == 0:
                do_bond = True
            elif l.find("DIHEDRAL") == 0:
                do_dihedral = True
            elif l.find("IMPHI") == 0:
                do_imphi = True
            elif do_bond:
                if len(tmp) > 0:
                    pair1 = tmp[0] + " " + tmp[1]
                    pair2 = tmp[1] + " " + tmp[0]
                    if (pair1 in pairs) or (pair2 in pairs):
                        ids.append(i)
                        print("Duplicate bonds: ", l[:-2])
                    else:
                        pairs.append(pair1)
                else:
                    do_bond = False
            elif do_angle:
                if len(tmp) > 0:
                    pair1 = tmp[0] + " " + tmp[1] + " " + tmp[2]
                    pair2 = tmp[2] + " " + tmp[1] + " " + tmp[0]
                    if (pair1 in triplets) or (pair2 in triplets):
                        ids.append(i)
                        print("Duplicate angles: ", l[:-2])
                    else:
                        triplets.append(pair1)
                else:
                    do_angle = False
            elif do_dihedral:
                pass
            elif do_imphi:
                if len(tmp) > 0:
                    pair1 = tmp[0] + " " + tmp[1] + " " + tmp[2] + " " + tmp[3]
                    if pair1 in imphis:
                        ids.append(i)
                        print("Duplicate imphi angles: ", l[:-2])
                    else:
                        imphis.append(pair1)
                    if tmp[0] == "X" and tmp[1] == "X" and tmp[2] == "c" and tmp[3] == "o":
                        string = """
X  X  c  o     1.100      2  180.00
X  n  c  o    10.500      2  180.00
X  o  c  o    10.500      2  180.00
"""
                        lines[i] = string
                        print("Replace imphi bug param for x-x-c-o : ", l[:-2])
                    if tmp[1] == "o" and tmp[2] == "c" and tmp[3] == "oh":
                        string = """
X  X  c  oh    1.100      2  180.00
X  n  c  oh   10.500      2  180.00
X  o  c  oh   10.500      2  180.00
"""
                        lines[i] = string
                        print("Replace imphi bug param for x-x-c-o : ", l[:-2])
                else:
                    do_imphi = False
                    break

    lines = [lines[i] for i in range(len(lines)) if i not in ids]
    with open(path, "w") as f:
        f.writelines(lines)
