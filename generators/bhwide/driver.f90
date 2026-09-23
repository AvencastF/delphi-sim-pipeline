! Standalone diagnostic wrapper; upstream BHWIDE routines remain unmodified.
program driver
 use, intrinsic :: ieee_arithmetic
 implicit none
 integer :: npar(100), nphot, i, j, attempts, seed, written
 real(8) :: xpar(100), p1(4),q1(4),p2(4),q2(4),phot(100,4)
 real(8) :: wtmod,wtcrud,wttrig,wtset(300)
 character(256) :: arg
 common /momset/ p1,q1,p2,q2,phot,nphot
 common /wgtall/ wtmod,wtcrud,wttrig,wtset
 if(command_argument_count()/=3) error stop 'usage: bhwide trials seed card.dat'
 call get_command_argument(1,arg);read(arg,*) attempts
 call get_command_argument(2,arg);read(arg,*) seed
 if(attempts<1.or.seed<1) error stop 'invalid count/seed'
 call seed_rng(seed)
 call get_command_argument(3,arg)
 npar=0;xpar=0d0
 open(20,file=trim(arg),status='old',action='read')
 read(20,*) npar(1),npar(2)
 read(20,*) xpar(1:15)
 close(20)
 if(mod(npar(1)/10,10)/=1) error stop 'diagnostic requires weighted mode'
 call glimit(50000)
 open(16,file='bhwide.log',status='new',action='write')
 call bhwide(-1,xpar,npar)
 open(21,file='events.raw',status='new',action='write')
 written=0
 do i=1,attempts
  call bhwide(0,xpar,npar)
  if(.not.ieee_is_finite(wtmod)) error stop 'nonfinite weight'
  ! BHCLEN clears rejected-event momenta: retain rejection count, not fake events.
  if(wtmod==0d0) cycle
  if(nphot<0.or.nphot>100) error stop 'invalid photon count'
  written=written+1
  write(21,'(A,1X,I0,1X,ES25.16E3,1X,I0)') 'E',i,wtmod,nphot
  ! Flip z to the project convention: electron beam along +z.
  call particle(21,11,4,q1)
  call particle(21,-11,4,p1)
  call particle(21,11,1,q2)
  call particle(21,-11,1,p2)
  do j=1,nphot
   call particle(21,22,1,phot(j,:))
  enddo
 enddo
 close(21)
 call bhwide(2,xpar,npar)
 close(16)
 open(22,file='normalization.dat',status='new',action='write')
 write(22,*) attempts,written,npar(10)
 ! XPAR(11) is RELATIVE statistical uncertainty, not an error in pb.
 write(22,'(3ES25.16E3)') xpar(10),xpar(11),xpar(20)
 close(22)
contains
 subroutine particle(unit,pdg,status,p)
  integer,intent(in)::unit,pdg,status
  real(8),intent(in)::p(4)
  if(.not.all(ieee_is_finite(p))) error stop 'nonfinite momentum'
  write(unit,'(2I8,4ES25.16E3)') pdg,status,p(1),p(2),-p(3),p(4)
 end subroutine
end program
