// SYNTHETIC SAMPLE CODE - not taken from any Conga repository.
namespace Clm.Api.Services
{
    public interface IAgreementService
    {
        Task<Agreement> GetAsync(string id);
        Task<Agreement> CreateAsync(AgreementRequest request);
        Task<Agreement> ActivateAsync(string id);
    }

    public class AgreementService : IAgreementService
    {
        private readonly IAgreementRepository _repository;
        private readonly IFeatureFlagService _features;

        public AgreementService(IAgreementRepository repository, IFeatureFlagService features)
        {
            _repository = repository;
            _features = features;
        }

        public Task<Agreement> GetAsync(string id) => _repository.GetAsync(id);

        public async Task<Agreement> CreateAsync(AgreementRequest request)
        {
            var agreement = new Agreement { Name = request.Name, Status = "Request" };
            return await _repository.SaveAsync(agreement);
        }

        public async Task<Agreement> ActivateAsync(string id)
        {
            var agreement = await _repository.GetAsync(id);
            if (_features.IsFeatureEnabled("clm.activation.publishToIndex"))
            {
                agreement.Indexed = true;
            }
            agreement.Status = "Activated";
            return await _repository.SaveAsync(agreement);
        }
    }
}
