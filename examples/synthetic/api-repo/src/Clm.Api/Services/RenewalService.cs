// SYNTHETIC SAMPLE CODE - not taken from any Conga repository.
using Microsoft.Extensions.Configuration;

namespace Clm.Api.Services
{
    public interface IRenewalService
    {
        Task<Agreement> RenewAsync(string id, RenewRequest request);
    }

    public class RenewalService : IRenewalService
    {
        private readonly IAgreementRepository _repository;
        private readonly IConfiguration _configuration;

        public RenewalService(IAgreementRepository repository, IConfiguration configuration)
        {
            _repository = repository;
            _configuration = configuration;
        }

        public async Task<Agreement> RenewAsync(string id, RenewRequest request)
        {
            var agreement = await _repository.GetAsync(id);
            var termMonths = request.TermMonths ?? _configuration.GetValue<int>("Renewal:DefaultTermMonths");
            agreement.EndDate = agreement.EndDate.AddMonths(termMonths);
            agreement.Status = "Renewed";
            return await _repository.SaveAsync(agreement);
        }
    }
}
