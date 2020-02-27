import random
import matplotlib.pyplot as plt
import pytest
import torch

import deepsmlm.generic.inout.load_calibration as load_cal
import deepsmlm.generic.plotting.frame_coord as plf
import deepsmlm.generic.psf_kernel as psf_kernel
import deepsmlm.generic.utils.test_utils as tutil


class TestPSF:

    @pytest.fixture(scope='class')
    def abs_psf(self):
        """
        Abstract PSF class fixture

        Returns:
            psf_kernel.PSF: abstract PSF
        """

        class PseudoAbsPSF(psf_kernel.PSF):
            def _forward_single_frame(self, xyz: torch.Tensor, weight: torch.Tensor):
                if xyz.numel() >= 1:
                    return torch.ones((32, 32)) * xyz[0, 0]
                else:
                    return torch.zeros((32, 32))

            def forward(self, xyz: torch.Tensor, weight: torch.Tensor, frame_ix: torch.Tensor, ix_low, ix_high):
                super().forward(xyz, weight, frame_ix, ix_low, ix_high)
                return self._forward_single_frame_wrapper(xyz, weight, frame_ix)

        return PseudoAbsPSF(None, None, None, None)

    def test_single_frame_wrapper(self, abs_psf):
        """
        Tests whether the general impl
        Args:
            abs_psf:

        Returns:

        """

        xyz = torch.Tensor([[15., 15., 0.], [0.5, 0.3, 0.]])
        phot = torch.ones_like(xyz[:, 0])
        frame_ix = torch.Tensor([1, -2]).int()

        frames = abs_psf._forward_single_frame_wrapper(xyz, phot, frame_ix, -2, 1)

        assert frames.dim() == 3
        assert (frames[0] == 0.5).all()
        assert (frames[1:3] == 0).all()
        assert (frames[-1] == 15).all()


class TestDeltaPSF:

    @pytest.fixture(scope='class')
    def delta_1px(self):
        return psf_kernel.DeltaPSF(xextent=(-0.5, 31.5),
                                   yextent=(-0.5, 31.5),
                                   img_shape=(32, 32))

    @pytest.fixture(scope='class')
    def delta_05px(self):
        return psf_kernel.DeltaPSF(xextent=(-0.5, 31.5),
                                   yextent=(-0.5, 31.5),
                                   img_shape=(64, 64))

    def test_forward(self, delta_1px, delta_05px):
        """
        Tests the implementation
        Args:
            delta_1px:
            delta_05px:

        Returns:

        """

        xyz = torch.Tensor([[0., 0., 0.], [15.0, 15.0, 200.], [4.8, 4.8, 200.], [4.79, 4.79, 500.]])
        phot = torch.ones_like(xyz[:, 0])
        frame_ix = torch.tensor([1, 0, 1, 1])

        """Run"""
        out_1px = delta_1px.forward(xyz, phot, frame_ix, 0, 2)
        out_05px = delta_05px.forward(xyz, phot, frame_ix, 0, 2)

        """Test"""
        assert out_1px.size() == torch.Size([3, 32, 32]), "Wrong output shape."
        assert out_05px.size() == torch.Size([3, 64, 64]), "Wrong output shape."

        assert out_1px[0, 15, 15] == 1.
        assert out_05px[0, 31, 31] == 1.

        assert out_1px[1, 0, 0] == 1.
        assert out_05px[1, 1, 1] == 1.

        assert (out_1px.unique() == torch.Tensor([0., 1.])).all()
        assert (out_05px.unique() == torch.Tensor([0., 1.])).all()


class TestGaussianExpect:

    @pytest.fixture(scope='class')
    def normgauss2d(self):
        return psf_kernel.GaussianExpect((-0.5, 63.5), (-0.5, 63.5), None, img_shape=(64, 64), sigma_0=1.5)

    @pytest.fixture(scope='class')
    def normgauss3d(self):
        return psf_kernel.GaussianExpect((-0.5, 63.5), (-0.5, 63.5), (-5000., 5000.), img_shape=(64, 64), sigma_0=1.5)

    def test_norm(self, normgauss2d, normgauss3d):
        xyz = torch.tensor([[32., 32., 0.]])
        phot = torch.tensor([1.])
        assert pytest.approx(normgauss2d.forward(xyz, phot).sum().item(), 0.05) == 1
        assert pytest.approx(normgauss3d.forward(xyz, phot).sum().item(), 0.05) == 1

    def test_peak_weight(self, normgauss2d, normgauss3d):
        normgauss2d.peak_weight = True
        normgauss3d.peak_weight = True

        xyz = torch.tensor([[32., 32., 0.]])
        phot = torch.tensor([1.])
        assert pytest.approx(normgauss2d.forward(xyz, phot).max().item(), 0.05) == 1
        assert pytest.approx(normgauss2d.forward(xyz, phot).max().item(), 0.05) == 1


class TestCubicSplinePSF:
    bead_cal = 'assets/bead_cal_for_testing.mat'

    @pytest.fixture(scope='class')
    def psf_cpu(self):
        xextent = (-0.5, 63.5)
        yextent = (-0.5, 63.5)
        img_shape = (64, 64)

        smap_psf = load_cal.SMAPSplineCoefficient(calib_file=self.bead_cal)
        psf = psf_kernel.CubicSplinePSF(xextent=xextent,
                                        yextent=yextent,
                                        img_shape=img_shape,
                                        roi_size=(32, 32),
                                        coeff=smap_psf.coeff,
                                        vx_size=(1., 1., 10),
                                        ref0=smap_psf.ref0,
                                        cuda=False)

        return psf

    @pytest.fixture(scope='class')
    def psf_cuda(self, psf_cpu):
        """
        Returns CUDA version of CPU implementation. Will make tests fail if not compiled with CUDA support enabled.
        Args:
            psf_cpu:

        Returns:

        """
        return psf_cpu.cuda()

    @pytest.fixture(scope='class')
    def onek_rois(self, psf_cpu):
        """
        Thousand random emitters in ROI

        Returns:
            xyz:
            phot:
            bg:
            n (int): number of emitters

        """
        n = 1000
        xyz = torch.rand((n, 3))
        xyz[:, :2] += psf_cpu.ref0[:2]
        xyz[:, 2] = xyz[:, 2] * 1000 - 500
        phot = torch.ones((n,)) * 10000
        bg = 50 * torch.ones((n,))

        return xyz, phot, bg, n

    @pytest.mark.xfail(not psf_kernel.CubicSplinePSF._cuda_compiled(), strict=True,
                       reason="Skipped because PSF implementation not compiled with CUDA support.")
    def test_ship(self, psf_cpu, psf_cuda):
        """
        Tests ships to CPU / CUDA
        Args:
            psf_cpu:
            psf_cuda:

        Returns:

        """
        import spline_psf_cuda

        """Test implementation state before"""
        assert isinstance(psf_cpu._spline_impl, spline_psf_cuda.PSFWrapperCPU)
        assert isinstance(psf_cuda._spline_impl, spline_psf_cuda.PSFWrapperCUDA)

        """Test implementation state after"""
        assert isinstance(psf_cpu.cuda()._spline_impl, spline_psf_cuda.PSFWrapperCUDA)
        assert isinstance(psf_cuda.cpu()._spline_impl, spline_psf_cuda.PSFWrapperCPU)

    @pytest.mark.xfail(not psf_kernel.CubicSplinePSF._cuda_compiled(), strict=True,
                       reason="Skipped because PSF implementation not compiled with CUDA support.")
    def test_roi_cuda_cpu(self, psf_cpu, psf_cuda, onek_rois):
        """
        Tests approximate equality of CUDA vs CPU implementation for a few ROIs

        Args:
            psf_cpu: psf implementation on CPU
            psf_cuda: psf implementation on CUDA

        """
        xyz, phot, bg, n = onek_rois
        phot = torch.ones_like(phot)

        roi_cpu = psf_cpu.forward_rois(xyz, phot)
        roi_cuda = psf_cuda.forward_rois(xyz, phot)

        assert tutil.tens_almeq(roi_cpu, roi_cuda, 1e-7)

    @pytest.mark.skip_plot
    def test_roi_visual(self, psf_cpu, onek_rois):
        xyz, phot, bg, n = onek_rois
        phot = torch.ones_like(phot)
        roi_cpu = psf_cpu.forward_rois(xyz, phot)

        """Additional Plotting if manual testing (comment out return statement)"""
        rix = random.randint(0, n - 1)
        plt.figure()
        plf.PlotFrameCoord(roi_cpu[rix], pos_tar=xyz[[rix]]).plot()
        plt.title("Random ROI sample.\nShould show a single emitter in the centre of a ROI.")
        plt.show()

    @pytest.mark.xfail(not psf_kernel.CubicSplinePSF._cuda_compiled(), strict=True,
                       reason="Skipped because PSF implementation not compiled with CUDA support.")
    def test_roi_drv_cuda_cpu(self, psf_cpu, psf_cuda, onek_rois):
        """
        Tests approximate equality of CUDA and CPU implementation for a few ROIs on the derivatives.

        Args:
            psf_cpu: psf implementation on CPU
            psf_cuda: psf implementation on CUDA

        """
        xyz, phot, bg, n = onek_rois
        phot = torch.ones_like(phot)

        drv_roi_cpu, _ = psf_cpu.derivative(xyz, phot, bg)
        drv_roi_cuda, _ = psf_cuda.derivative(xyz, phot, bg)

        assert tutil.tens_almeq(drv_roi_cpu, drv_roi_cuda, 1e-7)

    @pytest.mark.skip_plot
    def test_roi_visual(self, psf_cpu, onek_rois):
        xyz, phot, bg, n = onek_rois
        phot = torch.ones_like(phot)

        drv_rois, rois = psf_cpu.derivative(xyz, phot, bg)

        """Additional Plotting if manual testing."""
        rix = random.randint(0, n - 1)  # pick random sample
        dr = drv_rois[rix]
        r = rois[rix]
        xyzr = xyz[[rix]]

        plt.figure(figsize=(20, 12))

        plt.subplot(231)
        plf.PlotFrameCoord(r, pos_tar=xyzr).plot()
        plt.title("Random ROI sample.\nShould show a single emitter in the centre of a ROI.")

        plt.subplot(232)
        plf.PlotFrame(dr[0], plot_colorbar=True).plot()
        plt.title('d/dx')

        plt.subplot(233)
        plf.PlotFrame(dr[1], plot_colorbar=True).plot()
        plt.title('d/dy')

        plt.subplot(234)
        plf.PlotFrame(dr[2], plot_colorbar=True).plot()
        plt.title('d/dz')

        plt.subplot(235)
        plf.PlotFrame(dr[3], plot_colorbar=True).plot()
        plt.title('d/dphot')

        plt.subplot(236)
        plf.PlotFrame(dr[4], plot_colorbar=True).plot()
        plt.title('d/dbg')

        plt.show()


    @pytest.mark.xfail(not psf_kernel.CubicSplinePSF._cuda_compiled(), strict=True,
                       reason="Skipped because PSF implementation not compiled with CUDA support.")
    def test_frame_cuda_cpu(self, psf_cpu, psf_cuda):
        """
        Tests approximate equality of CUDA vs CPU implementation for a few frames

        Args:
            psf_cpu: psf fixture, CPU version
            psf_cuda: psf fixture, CUDA version

        Returns:

        """
        n = 10000
        xyz = torch.rand((n, 3)) * 64
        xyz[:, 2] = torch.randn_like(xyz[:, 2]) * 1000 - 500
        phot = torch.ones((n,))
        frame_ix = torch.randint(0, 500, size=(n,))

        frames_cpu = psf_cpu.forward(xyz, phot, frame_ix)
        frames_cuda = psf_cuda.forward(xyz, phot, frame_ix)

        assert tutil.tens_almeq(frames_cpu, frames_cuda, 1e-7)

    @pytest.mark.skip_plot
    def test_frame_visual(self, psf_cpu):
        n = 10
        xyz = torch.rand((n, 3)) * 64
        xyz[:, 2] = torch.randn_like(xyz[:, 2]) * 1000 - 500
        phot = torch.ones((n,))
        frame_ix = torch.zeros_like(phot).int()

        frames_cpu = psf_cpu.forward(xyz, phot, frame_ix)

        """Additional Plotting if manual testing (comment out return statement)."""
        plt.figure()
        plf.PlotFrameCoord(frames_cpu[0], pos_tar=xyz).plot()
        plt.title("Random Frame sample.\nShould show a single emitter distributed over a frame.")
        plt.show()

    def test_derivatives(self, psf_cpu, onek_rois):
        """
        Tests the derivate calculation

        Args:
            psf_cuda: psf fixture (see above)
            onek_rois: 1k roi fixture (see above)

        Returns:

        """
        """Setup"""
        xyz, phot, bg, n = onek_rois

        """Run"""
        drv, rois = psf_cpu.derivative(xyz, phot, bg)

        """Test"""
        assert drv.size() == torch.Size([n, psf_cpu.n_par, *psf_cpu.roi_size_px]), "Wrong dimension of derivatives."
        assert tutil.tens_almeq(drv[:, -1].unique(), torch.Tensor([0., 1.])), "Derivative of background must be 1 or 0."

        assert rois.size() == torch.Size([n, *psf_cpu.roi_size_px]), "Wrong dimension of ROIs."

    def test_fisher(self, psf_cpu, onek_rois):
        """
        Tests the fisher matrix calculation.

        Args:
            psf_cuda: psf fixture (see above)
            onek_rois: 1k roi fixture (see above)

        Returns:

        """
        """Setup"""
        xyz, phot, bg, n = onek_rois

        """Run"""
        fisher, rois = psf_cpu.fisher(xyz, phot, bg)

        """Test"""
        assert fisher.size() == torch.Size([n, psf_cpu.n_par, psf_cpu.n_par])

        assert rois.size() == torch.Size([n, *psf_cpu.roi_size_px]), "Wrong dimension of ROIs."

    @pytest.mark.xfail(float(torch.__version__[:3]) < 1.4,
                       reason="Pseudo inverse is not implemented in batch mode for older pytorch versions.")
    def test_crlb(self, psf_cpu, onek_rois):
        """
        Tests the crlb calculation
        Args:
            psf_cuda: psf fixture (see above)
            onek_rois: 1k roi fixture (see above)

        Returns:

        """
        """Setup"""
        xyz, phot, bg, n = onek_rois
        alt_inv = torch.pinverse

        """Run"""
        crlb, rois = psf_cpu.crlb(xyz, phot, bg)
        crlb_p, _ = psf_cpu.crlb(xyz, phot, bg, inversion=alt_inv)

        """Test"""
        assert crlb.size() == torch.Size([n, psf_cpu.n_par]), "Wrong CRLB dimension."
        assert (torch.Tensor([.01, .01, .02]) ** 2 <= crlb[:, :3]).all(), "CRLB in wrong range (lower bound)."
        assert (torch.Tensor([.1, .1, 100]) ** 2 >= crlb[:, :3]).all(), "CRLB in wrong range (upper bound)."

        diff_inv = (crlb_p - crlb).abs()

        assert tutil.tens_almeq(diff_inv[:, :2], torch.zeros_like(diff_inv[:, :2]), 1e-4)
        assert tutil.tens_almeq(diff_inv[:, 2], torch.zeros_like(diff_inv[:, 2]), 1e-1)
        assert tutil.tens_almeq(diff_inv[:, 3], torch.zeros_like(diff_inv[:, 3]), 1e2)
        assert tutil.tens_almeq(diff_inv[:, 4], torch.zeros_like(diff_inv[:, 4]), 1e-3)

        assert rois.size() == torch.Size([n, *psf_cpu.roi_size_px]), "Wrong dimension of ROIs."
